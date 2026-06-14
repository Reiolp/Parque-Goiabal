"""
Gera um CSV de preview mapeando arquivos em `uploads/` para chaves em um storage S3-compatible ou DigitalOcean Spaces.
Se variáveis de ambiente estiverem presentes, tenta verificar existência com head_object.
Escreve `scripts/migration_preview.csv`.

Uso:
  python scripts/preview_migration_csv.py

Saída: scripts/migration_preview.csv
Colunas: filename, local_path, storage_key, storage_url, exists_on_storage, action
"""
import os
import csv
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parents[1]
UPLOADS_DIR = BASE_DIR / 'uploads'
OUT_CSV = Path(__file__).resolve().parent / 'migration_preview.csv'

STORAGE_BUCKET = (
    os.environ.get('SPACES_BUCKET')
    or os.environ.get('DO_SPACES_BUCKET')
    or os.environ.get('AWS_S3_BUCKET')
)
STORAGE_REGION = (
    os.environ.get('SPACES_REGION')
    or os.environ.get('DO_SPACES_REGION')
    or os.environ.get('AWS_REGION', 'us-east-1')
)
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
STORAGE_ENDPOINT_URL = (
    os.environ.get('SPACES_ENDPOINT_URL')
    or os.environ.get('DO_SPACES_ENDPOINT_URL')
)
if not STORAGE_ENDPOINT_URL and (os.environ.get('SPACES_BUCKET') or os.environ.get('DO_SPACES_BUCKET')):
    STORAGE_ENDPOINT_URL = f'https://{STORAGE_REGION}.digitaloceanspaces.com'

STORAGE_BASE_URL = None
if STORAGE_BUCKET:
    if STORAGE_ENDPOINT_URL:
        endpoint_host = STORAGE_ENDPOINT_URL.replace('https://', '').replace('http://', '').rstrip('/')
        if endpoint_host.startswith(f'{STORAGE_BUCKET}.'):
            STORAGE_BASE_URL = f'https://{endpoint_host}'
        else:
            STORAGE_BASE_URL = f'https://{STORAGE_BUCKET}.{endpoint_host}'
    else:
        STORAGE_BASE_URL = f'https://{STORAGE_BUCKET}.s3.{STORAGE_REGION}.amazonaws.com'

use_storage = bool(STORAGE_BUCKET and STORAGE_ACCESS_KEY and STORAGE_SECRET_KEY)

if use_storage:
    try:
        import boto3
        from botocore.exceptions import ClientError
        client_args = {
            'aws_access_key_id': STORAGE_ACCESS_KEY,
            'aws_secret_access_key': STORAGE_SECRET_KEY,
            'region_name': STORAGE_REGION,
        }
        if STORAGE_ENDPOINT_URL:
            client_args['endpoint_url'] = STORAGE_ENDPOINT_URL
        s3 = boto3.client('s3', **client_args)
    except Exception as e:
        print('Falha ao inicializar boto3:', e)
        print('Seguindo sem verificação de storage (marcando exists_on_storage=unknown)')
        use_storage = False

if not UPLOADS_DIR.exists():
    print('Diretório uploads/ não existe. Nenhum arquivo a mapear.')
    sys.exit(0)

files = [p for p in sorted(UPLOADS_DIR.iterdir()) if p.is_file()]
if not files:
    print('Nenhum arquivo em uploads/.')
    sys.exit(0)

with open(OUT_CSV, 'w', newline='', encoding='utf-8') as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(['filename', 'local_path', 'storage_key', 'storage_url', 'exists_on_storage', 'action'])

    for f in files:
        key = f'uploads/{f.name}'
        storage_url = f'{STORAGE_BASE_URL}/{key}' if STORAGE_BASE_URL else ''
        exists = 'unknown'
        if use_storage:
            try:
                s3.head_object(Bucket=STORAGE_BUCKET, Key=key)
                exists = 'yes'
            except ClientError as e:
                code = e.response.get('Error', {}).get('Code')
                if code in ('404', 'NoSuchKey', 'NotFound'):
                    exists = 'no'
                else:
                    exists = 'unknown'
        action = 'skip (exists)' if exists == 'yes' else 'would upload'
        writer.writerow([f.name, str(f), key, storage_url, exists, action])

print(f'Preview gerado: {OUT_CSV}')
if use_storage:
    print('Verificação de storage efetuada (exists=yes/no/unknown).')
else:
    print('Sem credenciais de storage: exists_on_storage = unknown.')
