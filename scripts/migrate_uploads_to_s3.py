"""
Script para migrar arquivos da pasta `uploads/` para um bucket S3 e (opcionalmente)
atualizar o campo `img` em `Registro` e `foto` em `User` no banco `goiabal.db`.

Uso:
  # Dry-run (mostra o que seria feito)
  python scripts/migrate_uploads_to_s3.py --dry-run

  # Executa envio e atualiza o banco (faz backup antes)
  python scripts/migrate_uploads_to_s3.py --apply

Requisitos:
  - Variáveis de ambiente: SPACES_KEY, SPACES_SECRET, SPACES_BUCKET, SPACES_REGION
  - Opcional: SPACES_ENDPOINT_URL
  - Alternativas aceitas: DO_SPACES_KEY, DO_SPACES_SECRET, DO_SPACES_BUCKET, DO_SPACES_REGION, DO_SPACES_ENDPOINT_URL
  - boto3 instalado (já adicionado em requirements.txt)

Comportamento:
  - Faz upload de cada arquivo em `uploads/` para a chave `uploads/{filename}`
  - Se `--apply` for passado, copia `goiabal.db` para `goiabal.db.bak` e atualiza entradas que
    apontem para caminhos locais `/uploads/<filename>` substituindo pela URL pública do storage.
  - O script ignora arquivos que já existam no bucket (checa via head_object).
"""

import os
import sys
import argparse
from pathlib import Path
import sqlite3
import shutil
from urllib.parse import quote_plus

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print('boto3 não instalado. Rode: pip install boto3')
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parents[1]
UPLOADS_DIR = BASE_DIR / 'uploads'
DB_PATH = BASE_DIR / 'goiabal.db'

parser = argparse.ArgumentParser(description='Migrar uploads locais para storage S3-compatible e atualizar DB')
parser.add_argument('--apply', action='store_true', help='Executa o upload e atualiza o DB (default: dry-run)')
parser.add_argument('--prefix', default='uploads/', help='Prefixo/chave no bucket (default: uploads/)')
parser.add_argument('--public', action='store_true', help='Define ACL public-read ao fazer upload')
parser.add_argument('--endpoint', default=os.environ.get('SPACES_ENDPOINT_URL') or os.environ.get('DO_SPACES_ENDPOINT_URL'))
parser.add_argument('--region', default=os.environ.get('SPACES_REGION') or os.environ.get('DO_SPACES_REGION') or os.environ.get('AWS_REGION', 'us-east-1'))
args = parser.parse_args()

STORAGE_ACCESS_KEY = (
    os.environ.get('SPACES_KEY')
    or os.environ.get('DO_SPACES_KEY')
    or os.environ.get('AWS_ACCESS_KEY_ID')
)
STORAGE_SECRET_KEY = (
    os.environ.get('SPACES_SECRET')
    or os.environ.get('DO_SPACES_SECRET')
    or os.environ.get('AWS_SECRET_ACCESS_KEY')
)
STORAGE_BUCKET = (
    os.environ.get('SPACES_BUCKET')
    or os.environ.get('DO_SPACES_BUCKET')
    or os.environ.get('AWS_S3_BUCKET')
)
STORAGE_REGION = args.region
STORAGE_ENDPOINT_URL = args.endpoint

if not STORAGE_ENDPOINT_URL and (os.environ.get('SPACES_BUCKET') or os.environ.get('DO_SPACES_BUCKET')):
    STORAGE_ENDPOINT_URL = f'https://{STORAGE_REGION}.digitaloceanspaces.com'

if not STORAGE_BUCKET:
    print('Erro: defina a variável de ambiente SPACES_BUCKET ou DO_SPACES_BUCKET antes de rodar o script.')
    sys.exit(1)

client_args = {
    'aws_access_key_id': STORAGE_ACCESS_KEY,
    'aws_secret_access_key': STORAGE_SECRET_KEY,
    'region_name': STORAGE_REGION,
}
if STORAGE_ENDPOINT_URL:
    client_args['endpoint_url'] = STORAGE_ENDPOINT_URL

s3 = boto3.client(
    's3',
    **client_args
)

if STORAGE_ENDPOINT_URL:
    endpoint_host = STORAGE_ENDPOINT_URL.replace('https://', '').replace('http://', '').rstrip('/')
    if endpoint_host.startswith(f'{STORAGE_BUCKET}.'):
        STORAGE_BASE_URL = f'https://{endpoint_host}'
    else:
        STORAGE_BASE_URL = f'https://{STORAGE_BUCKET}.{endpoint_host}'
else:
    STORAGE_BASE_URL = f'https://{STORAGE_BUCKET}.s3.{STORAGE_REGION}.amazonaws.com'

files = []
if not UPLOADS_DIR.exists():
    print('Diretório uploads/ não existe; nada para migrar.')
    sys.exit(0)

for f in sorted(UPLOADS_DIR.iterdir()):
    if f.is_file():
        files.append(f)

if not files:
    print('Nenhum arquivo encontrado em uploads/.')
    sys.exit(0)

print(f'Arquivos encontrados: {len(files)}')

summary = []
for f in files:
    key = f'{args.prefix.rstrip("/")}/{f.name}'
    exists = True
    try:
        s3.head_object(Bucket=STORAGE_BUCKET, Key=key)
        exists = True
    except ClientError as e:
        code = e.response.get('Error', {}).get('Code')
        if code in ('404', 'NoSuchKey', 'NotFound'):
            exists = False
        else:
            # outras falhas (ex: 403) — reportar e continuar
            print(f'Warning: head_object para {key} falhou: {e}')
            exists = False

    action = 'skip (exists)' if exists else ('upload' if args.apply else 'would upload')
    print(f'{f.name}: {action}')
    summary.append((f, key, exists))

if not args.apply:
    print('\nModo dry-run. Rode com --apply para executar os uploads e atualizar o DB.')
    sys.exit(0)

# Faz backup do DB
if DB_PATH.exists():
    bak = DB_PATH.with_suffix('.db.bak')
    shutil.copy2(DB_PATH, bak)
    print(f'Backup do DB criado em: {bak}')
else:
    print('ATENÇÃO: banco de dados goiabal.db não encontrado; atualização do DB será ignorada.')

# Executa uploads
uploaded = []
for f, key, exists in summary:
    if exists:
        continue
    try:
        extra = {}
        if args.public:
            extra['ACL'] = 'public-read'
        content_type = None
        try:
            import mimetypes
            content_type = mimetypes.guess_type(str(f))[0]
            if content_type:
                extra['ContentType'] = content_type
        except Exception:
            pass
        with open(f, 'rb') as fh:
            s3.upload_fileobj(fh, STORAGE_BUCKET, key, ExtraArgs=extra)
        print(f'Uploaded: {f.name} -> {key}')
        uploaded.append((f, key))
    except Exception as e:
        print(f'Erro ao enviar {f.name}: {e}')

# Atualiza DB: substituir referências locais por URL de storage
if DB_PATH.exists():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # registros: campo img pode ser '/uploads/filename' ou caminho absoluto local
    for f, key in uploaded:
        local_patterns = [f"/uploads/{f.name}", f.name]
        storage_url = f"{STORAGE_BASE_URL}/{key}"
        # Atualizar Registro.img
        for pat in local_patterns:
            cur.execute("SELECT id, img FROM registro WHERE img LIKE ?", (f'%{pat}%',))
            rows = cur.fetchall()
            for row in rows:
                rid = row[0]
                print(f'Atualizando Registro id={rid}: {row[1]} -> {storage_url}')
                cur.execute("UPDATE registro SET img = ? WHERE id = ?", (storage_url, rid))
        # Atualizar User.foto
        for pat in local_patterns:
            cur.execute("SELECT id, foto FROM user WHERE foto LIKE ?", (f'%{pat}%',))
            rows = cur.fetchall()
            for row in rows:
                uid = row[0]
                print(f'Atualizando User id={uid}: {row[1]} -> {storage_url}')
                cur.execute("UPDATE user SET foto = ? WHERE id = ?", (storage_url, uid))
    conn.commit()
    conn.close()
    print('DB atualizado.')

print('Migração finalizada.')
