from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import boto3
from botocore.exceptions import ClientError
from sqlalchemy.orm import joinedload
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool
import os
from datetime import datetime

try:
    from supabase import create_client
except ImportError:
    create_client = None

app = Flask(__name__)
CORS(app, origins="*", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], 
     allow_headers=["*"])
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'goiabal.db')

def env(name):
    value = os.environ.get(name)
    return value.strip() if isinstance(value, str) else value

DATABASE_URL = env('DATABASE_URL')

# Debug: mostrar qual URL está sendo usada
print('DATABASE_URL configurado:', bool(DATABASE_URL))
if DATABASE_URL:
    print('DATABASE_URL começa com:', DATABASE_URL[:30] + '...')
    if DATABASE_URL.startswith(('http://', 'https://')):
        raise RuntimeError(
            'DATABASE_URL inválido: use a URL de conexão PostgreSQL completa (postgresql://...), '
            'não a URL do projeto Supabase.'
        )
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
else:
    print(f"⚠️  Usando SQLite local em: {DATABASE_PATH}")
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + DATABASE_PATH.replace('\\', '/')
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'connect_args': {'check_same_thread': False},
        'poolclass': NullPool,
    }
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# Storage configuration (optional). If SPACES_BUCKET or DO_SPACES_BUCKET is set, uploads will go to a DigitalOcean Spaces-compatible endpoint.
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
STORAGE_PUBLIC = os.environ.get('SPACES_PUBLIC', os.environ.get('S3_PUBLIC', '1')) == '1'

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

SUPABASE_URL = env('SUPABASE_URL')
SUPABASE_KEY = env('SUPABASE_SERVICE_ROLE_KEY') or env('SUPABASE_KEY') or env('SUPABASE_ANON_KEY')
SUPABASE_STORAGE_BUCKET = env('SUPABASE_STORAGE_BUCKET') or env('SUPABASE_BUCKET')
SUPABASE_CLIENT = None
SUPABASE_STORAGE_ENABLED = False
print(f"🔧 SUPABASE_URL: {SUPABASE_URL}")
print(f"🔧 SUPABASE_STORAGE_BUCKET: {SUPABASE_STORAGE_BUCKET}")
print(f"🔧 SUPABASE_KEY configurada: {bool(SUPABASE_KEY)}")
if SUPABASE_URL and SUPABASE_KEY and SUPABASE_STORAGE_BUCKET and create_client:
    try:
        SUPABASE_CLIENT = create_client(SUPABASE_URL, SUPABASE_KEY)
        SUPABASE_STORAGE_ENABLED = True
    except Exception as e:
        app.logger.error('Erro ao inicializar Supabase client: %s', e)

STORAGE_ENABLED = bool(STORAGE_BUCKET and STORAGE_ACCESS_KEY and STORAGE_SECRET_KEY)
if STORAGE_ENABLED:
    client_args = {
        'aws_access_key_id': STORAGE_ACCESS_KEY,
        'aws_secret_access_key': STORAGE_SECRET_KEY,
        'region_name': STORAGE_REGION,
    }
    if STORAGE_ENDPOINT_URL:
        client_args['endpoint_url'] = STORAGE_ENDPOINT_URL
    s3_client = boto3.client('s3', **client_args)

EXTERNAL_STORAGE_ENABLED = STORAGE_ENABLED or SUPABASE_STORAGE_ENABLED
print(f"🔧 STORAGE_ENABLED: {STORAGE_ENABLED}")
print(f"🔧 EXTERNAL_STORAGE_ENABLED: {EXTERNAL_STORAGE_ENABLED}")

if not EXTERNAL_STORAGE_ENABLED:
    app.logger.warning('Nenhum storage externo configurado. Os arquivos serão salvos localmente na pasta /uploads.')

def get_supabase_public_url(key):
    if not SUPABASE_URL or not SUPABASE_STORAGE_BUCKET:
        return None
    return f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{SUPABASE_STORAGE_BUCKET}/{key}"

def normalize_storage_key(key):
    normalized_key = key.replace('\\', '/').lstrip('/')
    normalized_key = os.path.normpath(normalized_key).replace('\\', '/')
    if normalized_key.startswith('../') or normalized_key == '..' or os.path.isabs(normalized_key):
        raise ValueError('Caminho de arquivo inválido')
    return normalized_key

def media_url(path):
    if not path:
        return None
    if path.startswith(('http://', 'https://', '/uploads/')):
        return path
    return f'/uploads/{path}'

def upload_file_to_storage(file_obj, key, content_type=None):
    """
    Tenta fazer o upload para o Supabase ou S3/Spaces. 
    Se nenhum estiver configurado, salva o arquivo localmente no servidor.
    """
    # 1. Tentativa com Supabase
    if SUPABASE_STORAGE_ENABLED:
        try:
            if hasattr(file_obj, 'seek'):
                file_obj.seek(0)
            file_data = file_obj.read() if hasattr(file_obj, 'read') else file_obj
            result = SUPABASE_CLIENT.storage.from_(SUPABASE_STORAGE_BUCKET).upload(key, file_data, content_type=content_type)
            if isinstance(result, dict) and result.get('error'):
                raise Exception(result.get('error'))
            return get_supabase_public_url(key)
        except Exception as e:
            app.logger.error('Erro de upload no Supabase Storage: %s', e)
            raise

    # 2. Tentativa com S3 / DigitalOcean Spaces
    if STORAGE_ENABLED:
        extra_args = {}
        if STORAGE_PUBLIC:
            extra_args['ACL'] = 'public-read'
        if content_type:
            extra_args['ContentType'] = content_type
        try:
            if hasattr(file_obj, 'seek'):
                file_obj.seek(0)
            s3_client.upload_fileobj(file_obj, STORAGE_BUCKET, key, ExtraArgs=extra_args)
            return f"{STORAGE_BASE_URL}/{key}"
        except ClientError as e:
            app.logger.error('Erro de upload no S3/Spaces Storage: %s', e)
            raise

    # 3. Fallback: Armazenamento Local (Caso não haja bucket ativo)
    try:
        normalized_key = normalize_storage_key(key)
        local_path = os.path.join(app.config['UPLOAD_FOLDER'], *normalized_key.split('/'))
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)
            
        file_obj.save(local_path)
        app.logger.info(f'Arquivo salvo localmente com sucesso: {local_path}')
        return normalized_key
    except Exception as e:
        app.logger.error('Erro ao salvar arquivo localmente: %s', e)
        raise

def get_uploaded_file(field_name):
    files = request.files.getlist(field_name)
    return next((file for file in files if file and file.filename), None)

def delete_storage_object_by_url(url_or_filename):
    """
    Remove o arquivo do bucket se for uma URL, ou do disco local se for apenas o nome do arquivo.
    """
    if not url_or_filename:
        return

    # Se não for uma URL da internet, assume que é um arquivo local da pasta uploads
    if not url_or_filename.startswith('http://') and not url_or_filename.startswith('https://'):
        try:
            normalized_key = normalize_storage_key(url_or_filename.replace('/uploads/', '', 1))
            local_path = os.path.join(app.config['UPLOAD_FOLDER'], *normalized_key.split('/'))
            if os.path.exists(local_path):
                os.remove(local_path)
                app.logger.info(f'Arquivo local deletado: {local_path}')
        except OSError as e:
            app.logger.error('Erro ao deletar arquivo local: %s', e)
        return

    # Deletar do Supabase
    if SUPABASE_STORAGE_ENABLED and SUPABASE_URL and SUPABASE_STORAGE_BUCKET:
        try:
            prefix = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{SUPABASE_STORAGE_BUCKET}/"
            if url_or_filename.startswith(prefix):
                key = url_or_filename[len(prefix):]
                SUPABASE_CLIENT.storage.from_(SUPABASE_STORAGE_BUCKET).remove([key])
                return
        except Exception as e:
            app.logger.error('Erro ao deletar no Supabase Storage: %s', e)
            return

    # Deletar do S3/Spaces
    if STORAGE_ENABLED and STORAGE_BASE_URL and url_or_filename.startswith(STORAGE_BASE_URL):
        key = url_or_filename[len(STORAGE_BASE_URL) + 1:]
        try:
            s3_client.delete_object(Bucket=STORAGE_BUCKET, Key=key)
        except ClientError as e:
            app.logger.error('Erro ao deletar no S3/Spaces Storage: %s', e)

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    sobrenome = db.Column(db.String(100))
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)
    foto = db.Column(db.String(300))  # path to profile image

class Registro(db.Model):
    __tablename__ = 'registros'
    id = db.Column(db.Integer, primary_key=True)
    especie = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)  # fauna or flora
    local = db.Column(db.String(200))
    desc = db.Column(db.Text)
    img = db.Column(db.String(300))  # path to image
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    data = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('registros', lazy=True))

class Denuncia(db.Model):
    __tablename__ = 'denuncias'
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50), nullable=False)  # incendio ou poluicao
    desc = db.Column(db.Text, nullable=False)
    local = db.Column(db.String(200))
    gravidade = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), default='aberto')  # aberto, andamento, resolvido
    img = db.Column(db.String(300))  # path to optional evidence image
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    data = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('denuncias', lazy=True))

class Curtida(db.Model):
    __tablename__ = 'curtidas'
    id = db.Column(db.Integer, primary_key=True)
    registro_id = db.Column(db.Integer, db.ForeignKey('registros.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    data = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('registro_id', 'usuario_id', name='uq_curtida_registro_usuario'),)

def create_admin_user():
    admin_email = os.environ.get('ADMIN_EMAIL', 'adm@adm.com')
    admin_password = os.environ.get('ADMIN_PASSWORD', 'adm123')
    admin_nome = os.environ.get('ADMIN_NOME', 'Administrador')
    if not User.query.filter_by(tipo='admin').first():
        if not User.query.filter_by(email=admin_email).first():
            admin = User(
                nome=admin_nome,
                sobrenome='',
                email=admin_email,
                senha=generate_password_hash(admin_password),
                tipo='admin',
                foto=None
            )
            db.session.add(admin)
            db.session.commit()
            print(f'Admin inicial criado: {admin_email}')

DB_AVAILABLE = True
with app.app_context():
    try:
        db.create_all()
        try:
            denuncia_columns = {column[1] for column in db.session.execute(text('PRAGMA table_info(denuncias)')).all()}
            if 'img' not in denuncia_columns:
                db.session.execute(text('ALTER TABLE denuncias ADD COLUMN img VARCHAR(300)'))
                db.session.commit()
        except Exception as e:
            app.logger.error('Erro ao garantir coluna img em denuncias: %s', e)
        create_admin_user()
    except Exception as e:
        DB_AVAILABLE = False
        app.logger.error('Erro ao conectar ao banco de dados no startup: %s', e)
        print('❌ Falha ao iniciar o banco de dados no startup. Verifique se o DATABASE_URL é acessível e se o host de deploy suporta a rota de rede.')

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'message': 'Servidor está funcionando!'}), 200

@app.route('/api/s3_check', methods=['GET'])
@app.route('/api/storage_check', methods=['GET'])
def storage_check():
    if SUPABASE_STORAGE_ENABLED:
        return jsonify({
            'storage_enabled': True,
            'backend': 'supabase',
            'bucket': SUPABASE_STORAGE_BUCKET,
            'url': SUPABASE_URL,
            'ok': True
        }), 200
    if not STORAGE_ENABLED:
        return jsonify({'storage_enabled': False, 'message': 'Armazenamento externo não está configurado (rodando localmente via fallback)'}), 200
    try:
        s3_client.head_bucket(Bucket=STORAGE_BUCKET)
        return jsonify({
            'storage_enabled': True,
            'backend': 's3',
            'bucket': STORAGE_BUCKET,
            'region': STORAGE_REGION,
            'endpoint': STORAGE_ENDPOINT_URL,
            'ok': True
        }), 200
    except ClientError as e:
        err = e.response.get('Error', {})
        return jsonify({
            'storage_enabled': True,
            'backend': 's3',
            'bucket': STORAGE_BUCKET,
            'region': STORAGE_REGION,
            'endpoint': STORAGE_ENDPOINT_URL,
            'ok': False,
            'error': err
        }), 200

@app.route('/api/register', methods=['POST'])
def register():
    try:
        print(f"\n{'='*60}")
        print(f"📝 Nova requisição de registro")
        print(f"{'='*60}")
        
        nome = request.form.get('nome')
        sobrenome = request.form.get('sobrenome', '')
        email = request.form.get('email')
        senha = request.form.get('senha')
        tipo = request.form.get('tipo')
        
        if not nome or not email or not senha or len(senha) < 6:
            return jsonify({'error': 'Dados inválidos'}), 400
        if tipo == 'admin':
            return jsonify({'error': 'Registro de administrador não permitido via site'}), 403
        if User.query.filter_by(email=email).first():
            return jsonify({'error': 'E-mail já cadastrado'}), 400
        
        foto_path = None
        if 'foto' in request.files:
            file = request.files['foto']
            if file and file.filename:
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)
                
                if file_size > 50 * 1024 * 1024:
                    return jsonify({'error': 'Foto de perfil muito grande. O tamanho máximo permitido é 50MB.'}), 413
                
                filename = secure_filename(file.filename)
                filename = f"profile_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                
                key = f'profiles/{filename}'
                try:
                    foto_path = upload_file_to_storage(file, key, content_type=file.content_type)
                except Exception as e:
                    print(f'❌ Erro ao salvar foto de perfil: {e}')
                    return jsonify({'error': 'Erro ao salvar foto de perfil'}), 500

        hashed_senha = generate_password_hash(senha)
        user = User(nome=nome, sobrenome=sobrenome, email=email, senha=hashed_senha, tipo=tipo, foto=foto_path)
        db.session.add(user)
        db.session.commit()
        
        foto_url = None
        if foto_path:
            foto_url = media_url(foto_path)
        
        return jsonify({'user': {'id': user.id, 'nome': user.nome, 'email': user.email, 'tipo': user.tipo, 'foto': foto_url}})
    except Exception as e:
        return jsonify({'error': f'Erro ao criar conta: {str(e)}'}), 500

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Dados inválidos'}), 400
    email = data.get('email')
    senha = data.get('senha')
    if not email or not senha:
        return jsonify({'error': 'Credenciais inválidas'}), 401
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.senha, senha):
        return jsonify({'error': 'Credenciais inválidas'}), 401
    foto_url = media_url(user.foto)
    return jsonify({'user': {'id': user.id, 'nome': user.nome, 'email': user.email, 'tipo': user.tipo, 'foto': foto_url}})

@app.route('/api/atualizar-foto', methods=['POST'])
def atualizar_foto():
    try:
        if 'usuario_id' not in request.form:
            return jsonify({'error': 'Não autorizado'}), 401
        usuario_id = int(request.form['usuario_id'])
        user = User.query.get(usuario_id)
        if not user:
            return jsonify({'error': 'Usuário não encontrado'}), 404
        
        if 'foto' not in request.files:
            return jsonify({'error': 'Nenhuma foto enviada'}), 400
        
        file = request.files['foto']
        if not file or not file.filename:
            return jsonify({'error': 'Arquivo inválido'}), 400
        
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > 50 * 1024 * 1024:
            return jsonify({'error': 'Foto muito grande. O tamanho máximo permitido é 50MB.'}), 413
        
        # Deleta a foto antiga se existir (funciona tanto para URL externa quanto arquivo local)
        if user.foto:
            delete_storage_object_by_url(user.foto)
        
        filename = secure_filename(file.filename)
        filename = f"profile_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
        
        key = f'perfis/{filename}'
        try:
            foto_path = upload_file_to_storage(file, key, content_type=file.content_type)
        except Exception as e:
            print(f'Erro ao enviar foto para storage: {e}')
            return jsonify({'error': 'Erro ao salvar foto'}), 500
        
        user.foto = foto_path
        db.session.commit()
        
        foto_url = media_url(user.foto)
        return jsonify({'message': 'Foto updated com sucesso', 'foto_url': foto_url}), 200
    except Exception as e:
        return jsonify({'error': f'Erro interno do servidor: {str(e)}'}), 500

@app.route('/api/registros', methods=['GET', 'POST'])
def registros():
    if request.method == 'POST':
        try:
            if 'usuario_id' not in request.form:
                return jsonify({'error': 'Não autorizado'}), 401
            usuario_id = int(request.form['usuario_id'])
            especie = request.form.get('especie')
            tipo = request.form.get('tipo')
            local = request.form.get('local', '')
            desc = request.form.get('desc', '')
            lat_str = request.form.get('lat')
            lng_str = request.form.get('lng')
            lat = float(lat_str) if lat_str and lat_str.strip() else None
            lng = float(lng_str) if lng_str and lng_str.strip() else None
            if not especie:
                return jsonify({'error': 'Nome da espécie obrigatório'}), 400
            
            img_path = None
            file = get_uploaded_file('img')
            if file:
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)
                
                if file_size > 50 * 1024 * 1024:
                    return jsonify({'error': 'Imagem muito grande. O tamanho máximo permitido é 50MB.'}), 413
                
                filename = secure_filename(file.filename)
                filename = f"registro_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                
                key = f'registros/{filename}'
                try:
                    img_path = upload_file_to_storage(file, key, content_type=file.content_type)
                except Exception as e:
                    print(f'Erro ao salvar imagem: {e}')
                    return jsonify({'error': 'Erro ao salvar imagem'}), 500
                        
            registro = Registro(especie=especie, tipo=tipo, local=local, desc=desc, img=img_path, lat=lat, lng=lng, usuario_id=usuario_id)
            db.session.add(registro)
            db.session.commit()
            return jsonify({'message': 'Registro criado'})
        except Exception as e:
            return jsonify({'error': f'Erro interno do servidor: {str(e)}'}), 500
    else:
        regs = Registro.query.options(joinedload(Registro.user)).all()
        result = []
        for r in regs:
            img_url = None
            if r.img:
                img_url = media_url(r.img)
            usuario_foto_url = None
            if r.user and r.user.foto:
                usuario_foto_url = media_url(r.user.foto)
            result.append({
                'id': r.id,
                'especie': r.especie,
                'tipo': r.tipo,
                'local': r.local,
                'desc': r.desc,
                'img': img_url,
                'lat': r.lat,
                'lng': r.lng,
                'data': r.data.strftime('%d/%m/%Y'),
                'usuario': r.user.nome if r.user else None,
                'usuario_foto': usuario_foto_url
            })
        return jsonify(result)

@app.route('/api/denuncias', methods=['GET', 'POST'])
def denuncias():
    if request.method == 'POST':
        if 'usuario_id' not in request.form:
            return jsonify({'error': 'Não autorizado'}), 401
        usuario_id = int(request.form['usuario_id'])
        tipo = request.form.get('tipo')
        desc = request.form.get('desc')
        local = request.form.get('local', '')
        gravidade = request.form.get('gravidade')
        lat = request.form.get('lat')
        lng = request.form.get('lng')
        def _to_float_or_none(v):
            if v is None or v == '':
                return None
            try:
                return float(v)
            except (ValueError, TypeError):
                return None
        lat = _to_float_or_none(lat)
        lng = _to_float_or_none(lng)
        if not tipo or not desc:
            return jsonify({'error': 'Dados obrigatórios faltando'}), 400

        img_path = None
        file = get_uploaded_file('img')
        if file:
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)

            if file_size > 50 * 1024 * 1024:
                return jsonify({'error': 'Imagem muito grande. O tamanho máximo permitido é 50MB.'}), 413

            filename = secure_filename(file.filename)
            filename = f"denuncia_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
            
            key = f'denuncias/{filename}'
            try:
                img_path = upload_file_to_storage(file, key, content_type=file.content_type)
            except Exception as e:
                print(f'Erro ao enviar imagem da denúncia: {e}')
                return jsonify({'error': 'Erro ao salvar imagem da denúncia'}), 500

        denuncia = Denuncia(tipo=tipo, desc=desc, local=local, gravidade=gravidade, lat=lat, lng=lng, usuario_id=usuario_id, img=img_path)
        db.session.add(denuncia)
        db.session.commit()
        return jsonify({'message': 'Denúncia criada'})
    else:
        dens = Denuncia.query.join(User).add_columns(
            Denuncia.id, Denuncia.tipo, Denuncia.desc, Denuncia.local, Denuncia.gravidade, Denuncia.status, Denuncia.lat, Denuncia.lng, Denuncia.data, Denuncia.img, Denuncia.usuario_id,
            User.nome.label('usuario')
        ).all()
        result = []
        for d in dens:
            img_url = None
            if d.img:
                img_url = media_url(d.img)
            result.append({
                'id': d.id,
                'tipo': d.tipo,
                'desc': d.desc,
                'local': d.local,
                'gravidade': d.gravidade,
                'status': d.status,
                'img': img_url,
                'lat': d.lat,
                'lng': d.lng,
                'data': d.data.strftime('%d/%m/%Y'),
                'usuario': d.usuario,
                'usuario_id': d.usuario_id
            })
        return jsonify(result)

@app.route('/api/denuncias/<int:denuncia_id>', methods=['DELETE'])
def delete_denuncia(denuncia_id):
    data = request.get_json() or {}
    usuario_id = data.get('usuario_id')
    if not usuario_id:
        return jsonify({'error': 'Não autorizado'}), 401
    user = User.query.get(usuario_id)
    if not user:
        return jsonify({'error': 'Usuário não encontrado'}), 404

    denuncia = Denuncia.query.get(denuncia_id)
    if not denuncia:
        return jsonify({'error': 'Denúncia não encontrada'}), 404

    if user.tipo != 'admin' and denuncia.usuario_id != usuario_id:
        return jsonify({'error': 'Acesso negado'}), 403

    if denuncia.img:
        try:
            delete_storage_object_by_url(denuncia.img)
        except Exception as e:
            app.logger.error('Erro ao apagar imagem da denúncia: %s', e)

    db.session.delete(denuncia)
    db.session.commit()
    return jsonify({'message': 'Denúncia excluída'})

@app.route('/api/stats')
def stats():
    usuarios = User.query.count()
    registros = Registro.query.count()
    denuncias = Denuncia.query.count()
    fauna = Registro.query.filter_by(tipo='fauna').count()
    flora = Registro.query.filter_by(tipo='flora').count()
    incendio = Denuncia.query.filter_by(tipo='incendio').count()
    poluicao = Denuncia.query.filter_by(tipo='poluicao').count()
    return jsonify({
        'usuarios': usuarios,
        'registros': registros,
        'denuncias': denuncias,
        'fauna': fauna,
        'flora': flora,
        'incendio': incendio,
        'poluicao': poluicao
    })

@app.route('/api/imagens')
def imagens():
    usuario_id = request.args.get('usuario_id', type=int)
    regs = Registro.query.filter(Registro.img.isnot(None)).outerjoin(User, Registro.usuario_id == User.id).add_columns(
        Registro.id, Registro.especie, Registro.tipo, Registro.local, Registro.desc, Registro.img, Registro.lat, Registro.lng, Registro.data, Registro.usuario_id,
        User.nome.label('usuario'), User.foto.label('usuario_foto')
    ).order_by(Registro.data.desc()).all()

    registro_ids = [r.id for r in regs]
    curtidas_por_registro = {}
    curtidas_usuario = set()
    if registro_ids:
        counts = db.session.query(
            Curtida.registro_id,
            db.func.count(Curtida.id)
        ).filter(Curtida.registro_id.in_(registro_ids)).group_by(Curtida.registro_id).all()
        curtidas_por_registro = {registro_id: count for registro_id, count in counts}

        if usuario_id:
            user_likes = Curtida.query.filter(
                Curtida.usuario_id == usuario_id,
                Curtida.registro_id.in_(registro_ids)
            ).all()
            curtidas_usuario = {like.registro_id for like in user_likes}
    
    result = []
    for r in regs:
        img_url = media_url(r.img)
        usuario_foto_url = None
        if r.usuario_foto:
            usuario_foto_url = media_url(r.usuario_foto)
            
        result.append({
            'id': r.id,
            'usuario_id': r.usuario_id,
            'especie': r.especie,
            'tipo': r.tipo,
            'local': r.local,
            'desc': r.desc,
            'img': img_url,
            'lat': r.lat,
            'lng': r.lng,
            'data': r.data.strftime('%d/%m/%Y'),
            'usuario': r.usuario or 'Usuário da comunidade',
            'usuario_foto': usuario_foto_url,
            'curtidas': int(curtidas_por_registro.get(r.id, 0)),
            'curtido': r.id in curtidas_usuario
        })
    return jsonify(result)

@app.route('/api/imagens/<int:registro_id>/curtir', methods=['POST'])
def curtir_imagem(registro_id):
    data = request.get_json() or {}
    usuario_id = data.get('usuario_id')
    if not usuario_id:
        return jsonify({'error': 'Faça login para curtir.'}), 401

    user = User.query.get(usuario_id)
    if not user:
        return jsonify({'error': 'Usuário não encontrado'}), 404

    registro = Registro.query.get(registro_id)
    if not registro or not registro.img:
        return jsonify({'error': 'Imagem não encontrada'}), 404

    existing = Curtida.query.filter_by(registro_id=registro_id, usuario_id=usuario_id).first()
    if existing:
        count = Curtida.query.filter_by(registro_id=registro_id).count()
        return jsonify({'message': 'Você já curtiu esta imagem.', 'curtidas': count, 'curtido': True}), 200

    curtida = Curtida(registro_id=registro_id, usuario_id=usuario_id)
    db.session.add(curtida)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()

    count = Curtida.query.filter_by(registro_id=registro_id).count()
    return jsonify({'message': 'Curtida registrada.', 'curtidas': count, 'curtido': True})

@app.route('/api/imagens/<int:registro_id>', methods=['DELETE'])
def delete_imagem(registro_id):
    data = request.get_json() or {}
    usuario_id = data.get('usuario_id')
    if not usuario_id:
        return jsonify({'error': 'Não autorizado'}), 401
    user = User.query.get(usuario_id)
    if not user:
        return jsonify({'error': 'Usuário não encontrado'}), 404

    registro = Registro.query.get(registro_id)
    if not registro:
        return jsonify({'error': 'Registro não encontrado'}), 404

    if user.tipo != 'admin' and registro.usuario_id != usuario_id:
        return jsonify({'error': 'Acesso negado'}), 403

    if registro.img:
        try:
            delete_storage_object_by_url(registro.img)
        except Exception as e:
            app.logger.error('Erro ao apagar imagem associada: %s', e)

    Curtida.query.filter_by(registro_id=registro.id).delete()
    db.session.delete(registro)
    db.session.commit()
    return jsonify({'message': 'Registro excluído'})

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    from flask import make_response
    response = make_response(send_from_directory(app.config['UPLOAD_FOLDER'], filename))
    response.cache_control.max_age = 2592000  # 30 dias de cache
    response.cache_control.public = True
    return response

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    
    print(f"🚀 Iniciando servidor em http://{host}:{port}")
    print(f"Debug mode: {debug}")
    
    app.run(
        host=host,
        port=port,
        debug=debug
    )
