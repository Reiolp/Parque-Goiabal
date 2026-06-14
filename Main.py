from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import boto3
from botocore.exceptions import ClientError
from sqlalchemy.orm import joinedload
from sqlalchemy import text
import os
from datetime import datetime

app = Flask(__name__)
CORS(app, origins="*", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], 
     allow_headers=["*"])
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'goiabal.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + DATABASE_PATH.replace('\\', '/')
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

def upload_file_to_storage(file_obj, key, content_type=None):
    extra_args = {}
    if STORAGE_PUBLIC:
        extra_args['ACL'] = 'public-read'
    if content_type:
        extra_args['ContentType'] = content_type
    try:
        s3_client.upload_fileobj(file_obj, STORAGE_BUCKET, key, ExtraArgs=extra_args)
    except ClientError as e:
        app.logger.error('Storage upload error: %s', e)
        raise
    return f"{STORAGE_BASE_URL}/{key}"

def delete_storage_object_by_url(url):
    if not STORAGE_ENABLED or not url:
        return
    if STORAGE_BASE_URL and url.startswith(STORAGE_BASE_URL):
        key = url[len(STORAGE_BASE_URL) + 1:]
        try:
            s3_client.delete_object(Bucket=STORAGE_BUCKET, Key=key)
        except ClientError as e:
            app.logger.error('Storage delete error: %s', e)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    sobrenome = db.Column(db.String(100))
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)
    foto = db.Column(db.String(300))  # path to profile image

class Registro(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    especie = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)  # fauna or flora
    local = db.Column(db.String(200))
    desc = db.Column(db.Text)
    img = db.Column(db.String(300))  # path to image
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    usuario_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    data = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('registros', lazy=True))

class Denuncia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50), nullable=False)  # incendio ou poluicao
    desc = db.Column(db.Text, nullable=False)
    local = db.Column(db.String(200))
    gravidade = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), default='aberto')  # aberto, andamento, resolvido
    img = db.Column(db.String(300))  # path to optional evidence image
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    usuario_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    data = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('denuncias', lazy=True))

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

with app.app_context():
    db.create_all()
    try:
        denuncia_columns = {column[1] for column in db.session.execute(text('PRAGMA table_info(denuncia)')).all()}
        if 'img' not in denuncia_columns:
            db.session.execute(text('ALTER TABLE denuncia ADD COLUMN img VARCHAR(300)'))
            db.session.commit()
    except Exception as e:
        app.logger.error('Erro ao garantir coluna img em denuncia: %s', e)
    create_admin_user()

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'message': 'Servidor está funcionando!'}), 200


@app.route('/api/s3_check', methods=['GET'])
@app.route('/api/storage_check', methods=['GET'])
def storage_check():
    """Verifica se a configuração de armazenamento externo está ativa e tenta acessar o bucket.
    Use para validar que as variáveis de ambiente foram configuradas corretamente.
    """
    if not STORAGE_ENABLED:
        return jsonify({'storage_enabled': False, 'message': 'Armazenamento externo não está configurado (bucket ou credenciais ausentes)'}), 200
    try:
        # tenta head_bucket para verificar permissões
        s3_client.head_bucket(Bucket=STORAGE_BUCKET)
        return jsonify({
            'storage_enabled': True,
            'bucket': STORAGE_BUCKET,
            'region': STORAGE_REGION,
            'endpoint': STORAGE_ENDPOINT_URL,
            'ok': True
        }), 200
    except ClientError as e:
        err = e.response.get('Error', {})
        return jsonify({
            'storage_enabled': True,
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
        print(f"Content-Type: {request.content_type}")
        print(f"Form data: {dict(request.form)}")
        
        nome = request.form.get('nome')
        sobrenome = request.form.get('sobrenome', '')
        email = request.form.get('email')
        senha = request.form.get('senha')
        tipo = request.form.get('tipo')
        
        print(f"\nDados recebidos:")
        print(f"  Nome: {nome}")
        print(f"  Email: {email}")
        print(f"  Tipo: {tipo}")
        
        if not nome or not email or not senha or len(senha) < 6:
            print(f"❌ Validação falhou: dados inválidos")
            return jsonify({'error': 'Dados inválidos'}), 400
        if tipo == 'admin':
            print(f"❌ Tipo admin não permitido")
            return jsonify({'error': 'Registro de administrador não permitido via site'}), 403
        if User.query.filter_by(email=email).first():
            print(f"❌ E-mail {email} já cadastrado")
            return jsonify({'error': 'E-mail já cadastrado'}), 400
        
        foto_path = None
        if 'foto' in request.files:
            file = request.files['foto']
            if file and file.filename:
                print(f"📸 Processando foto: {file.filename}")
                # Verificar tamanho do arquivo (50MB máximo para fotos de perfil)
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)
                
                if file_size > 50 * 1024 * 1024:
                    print(f"❌ Foto muito grande: {file_size} bytes")
                    return jsonify({'error': 'Foto de perfil muito grande. O tamanho máximo permitido é 50MB.'}), 413
                
                filename = secure_filename(file.filename)
                filename = f"profile_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                if STORAGE_ENABLED:
                    key = f'profiles/{filename}'
                    try:
                        foto_path = upload_file_to_storage(file, key, content_type=file.content_type)
                        print(f"✓ Foto enviada para storage: {foto_path}")
                    except Exception as e:
                        print(f'❌ Erro ao enviar foto para storage: {e}')
                        return jsonify({'error': 'Erro ao salvar foto de perfil'}), 500
                else:
                    foto_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    try:
                        file.save(foto_path)
                        print(f"✓ Foto salva em: {foto_path}")
                    except Exception as e:
                        print(f'❌ Erro ao salvar foto: {e}')
                        return jsonify({'error': 'Erro ao salvar foto de perfil'}), 500

        print(f"\n🔐 Criando hash de senha...")
        hashed_senha = generate_password_hash(senha)
        user = User(nome=nome, sobrenome=sobrenome, email=email, senha=hashed_senha, tipo=tipo, foto=foto_path)
        db.session.add(user)
        db.session.commit()
        
        foto_url = None
        if foto_path:
            if isinstance(foto_path, str) and foto_path.startswith('http'):
                foto_url = foto_path
            else:
                foto_url = f'/uploads/{os.path.basename(foto_path)}'
        
        print(f"✅ Usuário criado com sucesso!")
        print(f"   ID: {user.id}")
        print(f"   Email: {user.email}")
        print(f"{'='*60}\n")
        
        return jsonify({'user': {'id': user.id, 'nome': user.nome, 'email': user.email, 'tipo': user.tipo, 'foto': foto_url}})
    except Exception as e:
        import traceback
        print(f'❌ ERRO NO REGISTRO: {e}')
        print(f'Traceback:\n{traceback.format_exc()}')
        print(f"{'='*60}\n")
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
    foto_url = None
    if user.foto:
        if isinstance(user.foto, str) and user.foto.startswith('http'):
            foto_url = user.foto
        else:
            foto_url = f'/uploads/{os.path.basename(user.foto)}'
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
        
        # Validar tamanho
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > 50 * 1024 * 1024:
            return jsonify({'error': 'Foto muito grande. O tamanho máximo permitido é 50MB.'}), 413
        
        # Deletar foto antiga se existir
        if user.foto and not user.foto.startswith('http'):
            try:
                os.remove(user.foto)
            except OSError:
                pass
        elif user.foto and STORAGE_ENABLED and STORAGE_BASE_URL and user.foto.startswith(STORAGE_BASE_URL):
            delete_storage_object_by_url(user.foto)
        
        # Salvar nova foto
        filename = secure_filename(file.filename)
        filename = f"profile_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
        
        if STORAGE_ENABLED:
            key = f'perfis/{filename}'
            try:
                foto_path = upload_file_to_storage(file, key, content_type=file.content_type)
            except Exception as e:
                print(f'Erro ao enviar foto para storage: {e}')
                return jsonify({'error': 'Erro ao salvar foto'}), 500
        else:
            foto_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(foto_path)
        
        user.foto = foto_path
        db.session.commit()
        
        foto_url = f'/uploads/{os.path.basename(foto_path)}' if not foto_path.startswith('http') else foto_path
        
        return jsonify({'message': 'Foto atualizada com sucesso', 'foto_url': foto_url}), 200
    except Exception as e:
        print(f"Erro ao atualizar foto: {e}")
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
            if 'img' in request.files:
                file = request.files['img']
                if file and file.filename:
                    # Verificar tamanho do arquivo (50MB máximo)
                    file.seek(0, os.SEEK_END)
                    file_size = file.tell()
                    file.seek(0)
                    
                    if file_size > 50 * 1024 * 1024:
                        return jsonify({'error': 'Imagem muito grande. O tamanho máximo permitido é 50MB.'}), 413
                    
                    filename = secure_filename(file.filename)
                    filename = f"registro_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                    if STORAGE_ENABLED:
                        key = f'registros/{filename}'
                        try:
                            img_path = upload_file_to_storage(file, key, content_type=file.content_type)
                        except Exception as e:
                            print(f'Erro ao enviar imagem para storage: {e}')
                            return jsonify({'error': 'Erro ao salvar imagem'}), 500
                    else:
                        img_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                        file.save(img_path)
            registro = Registro(especie=especie, tipo=tipo, local=local, desc=desc, img=img_path, lat=lat, lng=lng, usuario_id=usuario_id)
            db.session.add(registro)
            db.session.commit()
            return jsonify({'message': 'Registro criado'})
        except Exception as e:
            print(f"Erro ao criar registro: {e}")
            return jsonify({'error': f'Erro interno do servidor: {str(e)}'}), 500
    else:
        regs = Registro.query.options(joinedload(Registro.user)).all()
        result = []
        for r in regs:
            # normalize img and usuario_foto to public URLs
            img_url = None
            if r.img:
                if isinstance(r.img, str) and r.img.startswith('http'):
                    img_url = r.img
                else:
                    img_url = f'/uploads/{os.path.basename(r.img)}'
            usuario_foto_url = None
            if r.user and r.user.foto:
                if isinstance(r.user.foto, str) and r.user.foto.startswith('http'):
                    usuario_foto_url = r.user.foto
                else:
                    usuario_foto_url = f'/uploads/{os.path.basename(r.user.foto)}'
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
        if lat: lat = float(lat)
        if lng: lng = float(lng)
        if not tipo or not desc:
            return jsonify({'error': 'Dados obrigatórios faltando'}), 400

        img_path = None
        if 'img' in request.files:
            file = request.files['img']
            if file and file.filename:
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)

                if file_size > 50 * 1024 * 1024:
                    return jsonify({'error': 'Imagem muito grande. O tamanho máximo permitido é 50MB.'}), 413

                filename = secure_filename(file.filename)
                filename = f"denuncia_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                if STORAGE_ENABLED:
                    key = f'denuncias/{filename}'
                    try:
                        img_path = upload_file_to_storage(file, key, content_type=file.content_type)
                    except Exception as e:
                        print(f'Erro ao enviar imagem da denúncia para storage: {e}')
                        return jsonify({'error': 'Erro ao salvar imagem da denúncia'}), 500
                else:
                    img_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(img_path)

        denuncia = Denuncia(tipo=tipo, desc=desc, local=local, gravidade=gravidade, lat=lat, lng=lng, usuario_id=usuario_id, img=img_path)
        db.session.add(denuncia)
        db.session.commit()
        return jsonify({'message': 'Denúncia criada'})
    else:
        dens = Denuncia.query.join(User).add_columns(
            Denuncia.id, Denuncia.tipo, Denuncia.desc, Denuncia.local, Denuncia.gravidade, Denuncia.status, Denuncia.lat, Denuncia.lng, Denuncia.data, Denuncia.img,
            User.nome.label('usuario')
        ).all()
        result = []
        for d in dens:
            img_url = None
            if d.img:
                if isinstance(d.img, str) and d.img.startswith('http'):
                    img_url = d.img
                else:
                    img_url = f'/uploads/{os.path.basename(d.img)}'
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
                'usuario': d.usuario
            })
        return jsonify(result)

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
    regs = Registro.query.filter(Registro.img.isnot(None)).join(User).add_columns(
        Registro.id, Registro.especie, Registro.tipo, Registro.local, Registro.desc, Registro.img, Registro.lat, Registro.lng, Registro.data, Registro.usuario_id,
        User.nome.label('usuario'), User.foto.label('usuario_foto')
    ).order_by(Registro.data.desc()).all()
    
    result = []
    for r in regs:
        result.append({
            'id': r.id,
            'usuario_id': r.usuario_id,
            'especie': r.especie,
            'tipo': r.tipo,
            'local': r.local,
            'desc': r.desc,
            'img': f'/uploads/{os.path.basename(r.img)}' if r.img else None,
            'lat': r.lat,
            'lng': r.lng,
            'data': r.data.strftime('%d/%m/%Y'),
            'usuario': r.usuario,
            'usuario_foto': f'/uploads/{os.path.basename(r.usuario_foto)}' if r.usuario_foto else None
        })
    return jsonify(result)

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

    # Permitir exclusão se for admin ou se for o dono da imagem
    if user.tipo != 'admin' and registro.usuario_id != usuario_id:
        return jsonify({'error': 'Acesso negado'}), 403

    if registro.img:
        # se imagem estiver no storage externo (URL), delete do storage, caso contrário delete arquivo local
        try:
            if STORAGE_ENABLED and isinstance(registro.img, str) and STORAGE_BASE_URL and registro.img.startswith(STORAGE_BASE_URL):
                delete_storage_object_by_url(registro.img)
            else:
                try:
                    os.remove(registro.img)
                except OSError:
                    pass
        except Exception as e:
            app.logger.error('Erro ao apagar imagem associada: %s', e)
    db.session.delete(registro)
    db.session.commit()
    return jsonify({'message': 'Registro excluído'})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    from flask import make_response
    response = make_response(send_from_directory(app.config['UPLOAD_FOLDER'], filename))
    # Permitir cache longo (30 dias) já que os nomes de arquivo são únicos com timestamp
    response.cache_control.max_age = 2592000  # 30 dias em segundos
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
