# 🌿 Parque-Goaibal

Plataforma web open source para **registro da biodiversidade e denúncias ambientais** no Parque do Goiabal, em Ituiutaba - MG.

O projeto foi desenvolvido com o objetivo de aproximar comunidade, visitantes e pesquisadores da preservação ambiental através do registro colaborativo de espécies e comunicação de ocorrências ambientais.

---

## 📷 Visão Geral

O Parque-Goaibal permite que usuários:

🦋 Registrem espécies de fauna e flora  
📸 Compartilhem imagens da biodiversidade local  
🚨 Reportem problemas ambientais (incêndios, poluição etc.)  
👤 Criem contas e acompanhem suas contribuições  
🗺️ Visualizem registros realizados pela comunidade  

---

## ✨ Funcionalidades

### 👤 Sistema de Usuários
- Cadastro de usuários
- Login com autenticação
- Upload de foto de perfil
- Perfil individual

### 🦋 Registro de Biodiversidade
- Cadastro de espécies
- Upload de imagens
- Informações de localização
- Histórico de registros

### 🚨 Sistema de Denúncias
- Registro de ocorrências ambientais
- Classificação por tipo
- Controle de status

### 📸 Galeria Comunitária
- Feed com imagens da comunidade
- Curtidas em registros
- Visualização ampliada das imagens

### ☁️ Armazenamento
- Upload e gerenciamento de arquivos com Supabase Storage
- Fallback para armazenamento local

---

## 🛠️ Tecnologias Utilizadas

### Frontend
- HTML5
- CSS3
- JavaScript
- Leaflet (Mapas)

### Backend
- Python
- Flask
- Flask SQLAlchemy
- Flask CORS

### Banco de Dados
- SQLite (desenvolvimento)
- PostgreSQL (produção)

### Infraestrutura
- Railway
- Supabase

---

## 🚀 Como executar localmente

### 1. Clone o repositório

```bash
git clone https://github.com/SEU-USUARIO/Parque-Goaibal.git
```

### 2. Entre na pasta

```bash
cd Parque-Goaibal
```

### 3. Crie um ambiente virtual

Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

Linux/Mac:

```bash
python3 -m venv venv
source venv/bin/activate
```

### 4. Instale as dependências

```bash
pip install -r requirements.txt
```

### 5. Configure as variáveis de ambiente

Crie um arquivo `.env`

```env
DATABASE_URL=

SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_STORAGE_BUCKET=

ADMIN_EMAIL=
ADMIN_PASSWORD=
ADMIN_NOME=
```

### 6. Execute o projeto

```bash
python Main.py
```

Servidor disponível em:

```txt
http://localhost:5000
```

---

## 📁 Estrutura do Projeto

```txt
Parque-Goaibal/
│
├── Main.py
├── index.html
├── uploads/
├── goiabal.db
├── requirements.txt
└── README.md
```

---

## 🔌 Principais Endpoints

| Método | Endpoint | Descrição |
|---------|----------|-----------|
| POST | `/api/register` | Criar conta |
| POST | `/api/login` | Login |
| GET | `/api/registros` | Listar registros |
| POST | `/api/registros` | Criar registro |
| GET | `/api/health` | Status da API |
| GET | `/api/storage_check` | Verificar armazenamento |

---

## 🌍 Deploy

Projeto hospedado utilizando Railway:

https://railway.com/project/7e679b58-7e6f-42e2-91e5-23d95d72a818/service/e132ac30-c2eb-4a5a-96b4-83e99e346bb4?environmentId=abc6136d-1a33-4297-8601-ae6ff5dfdb92

---

## 👥 Equipe

- Luís Octavio Lacerda Pereira
- Douglas Santana de Oliveira
- Gustavo Marques
- Lucas Freitas

---

## 🤝 Contribuições

Contribuições são bem-vindas.

Para contribuir:

1. Faça um fork
2. Crie uma branch

```bash
git checkout -b minha-feature
```

3. Commit

```bash
git commit -m "feat: nova funcionalidade"
```

4. Push

```bash
git push origin minha-feature
```

5. Abra um Pull Request

---

## 📄 Licença

Este projeto está licenciado sob a **GNU General Public License v3.0 (GPL-3.0)**.

Você pode utilizar, modificar e redistribuir o código respeitando os termos da licença.

Consulte o arquivo:

```txt
LICENSE
```

---

<div align="center">

Feito para incentivar tecnologia, comunidade e preservação ambiental 🌿

</div>
