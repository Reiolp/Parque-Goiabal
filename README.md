# Deploy do site em nuvem

Este projeto pode ser hospedado em um serviço como Render, Railway ou PythonAnywhere.

## Passo a passo para Render

1. Crie uma conta em https://render.com
2. Crie um novo Web Service.
3. Conecte seu repositório Git ou faça deploy manual.
4. Use as configurações:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn Main:app`
   - Environment: `PORT` é definido automaticamente pelo Render.

## Passo a passo para Railway

1. Crie uma conta em https://railway.app
2. Faça novo projeto e escolha `Deploy from GitHub` ou `Deploy from repo`.
3. No comando de start, escolha: `gunicorn Main:app`
4. O Railway define a variável `PORT` automaticamente.

## Observações

- O aplicativo já serve `index.html` e o endpoint `/uploads/<filename>` para imagens.
- Render define `PORT` automaticamente.
- O arquivo `render.yaml` também está incluído para facilitar o deploy automático no Render.
- Em produção, remova `debug=True` ou defina `FLASK_DEBUG=0`.
- O backend não roda no GitHub Pages. O GitHub Pages serve apenas o frontend estático.
- Para o frontend hospedado no GitHub Pages, use o URL público do backend (por exemplo `https://goiabal-site.onrender.com`) na variável `API_BASE_URL` de `index.html`.
- Se o seu serviço Render tiver outro domínio, atualize `API_BASE_URL` com esse URL.
- Atenção: o banco SQLite e uploads em disco são efêmeros no Render; use armazenamento externo para dados persistentes se precisar.
- Caso use outro serviço, garanta que o deploy execute `pip install -r requirements.txt` e `gunicorn Main:app`.

## DigitalOcean Spaces

1. Crie um Space no painel da DigitalOcean.
2. Defina as variáveis de ambiente no Render ou no serviço de hospedagem:
   - `SPACES_BUCKET` = nome do Space
   - `SPACES_REGION` = região do Space (`nyc3`, `sfo2`, `ams3`, etc.)
   - `SPACES_KEY` = access key do Space
   - `SPACES_SECRET` = secret key do Space
   - `SPACES_ENDPOINT_URL` = `https://<REGION>.digitaloceanspaces.com`
   - Opcional: `SPACES_PUBLIC=1` para publicar objetos como `public-read`
3. O backend também aceita variáveis alternativas com prefixo `DO_SPACES_`.
4. Verifique a configuração com `GET /api/storage_check`.

## Comandos úteis

- Verificar antes de migrar:
  - `python scripts/preview_migration_csv.py`
- Migrar os arquivos atuais de `uploads/` para o Space e atualizar o DB:
  - `python scripts/migrate_uploads_to_s3.py --apply --public`
- Testar o storage em execução local:
  - `curl http://127.0.0.1:5000/api/storage_check`
- No Render, se o frontend estiver em outro domínio, use o URL do backend em `index.html`.
