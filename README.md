<div align="center">
   <img height="200" alt="VALLET_logo" src="https://github.com/user-attachments/assets/c016879c-235f-423f-b553-08cb60cf02e3" />
   
   <a href="https://git.io/typing-svg"><img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=600&size=26&pause=10000&color=3b5042&width=600&height=55&lines=Sistema+de+Gest%C3%A3o+de+Estacionamentos" alt="Typing SVG" /></a>
</div>

<p>
Seja bem-vindo ao projeto <b>Vallet</b>, um sistema multiplataforma que busca otimizar e modernizar o processo de <b>reserva, monitoramento e administração de vagas de estacionamento,</b> beneficiando tanto motoristas quanto os administradores de estacionamentos.
</p>

>Este repositório inclui a lógica da aplicação para conexão com o banco e entre todos os sistemas

<h3>Verifique outras partes do nosso projeto</h3>

 | Módulo / Repositório | Descrição | Link de Acesso |
| :--- | :--- | :--- |
| **ValletWeb** (Gestores) | Dashboards e controle de ocupação para gestores de estacionamento. | [Repositório Web](https://github.com/Pereira-Sah/ValletWeb) |
| **ValletApp** (Android) | Aplicativo móvel voltado para motoristas e usuários finais. | [Repositório Android](https://github.com/lariiscriis/ValletProjeto) |
| **ValletAPI** | API backend para conexão e gerenciamento de todo o ecossistema. | [Repositório API](https://github.com/Almile/ValletAPI) |
| **ValletIOT** | Sistema de leitura de placas (LPR) com uso de webcam. | [Repositório IOT](https://github.com/Almile/ValletIOT) |
| **ValletDesktop** | Sistema desktop voltado para os administradores gerais. | [Repositório Desktop](https://github.com/Almile/valletDesktop) |

<br>
<p align="center">
  <img src="https://img.shields.io/badge/Python-637365?style=for-the-badge&logo=kotlin&logoColor=white" />
  <img src="https://img.shields.io/badge/Firebase-3b5042?style=for-the-badge&logo=android&logoColor=white" />
  <img src="https://img.shields.io/badge/Cloudinary-cbd9c5?style=for-the-badge&logo=firebase&logoColor=white" />
  <img src="https://img.shields.io/badge/Mercado-Pago-637365?style=for-the-badge&logo=google-cloud&logoColor=white" />
  <img src="https://img.shields.io/badge/Firestore-3b5042?style=for-the-badge&logo=architecture&logoColor=white" />
</p>
<br>


## Pré-requisitos
1. Ter o **Python 3.10+** instalado.
2. Ter o **VS Code** instalado.

## Como rodar o projeto

Abra o terminal na pasta do projeto e siga estes passos:

### 1. Criar o ambiente virtual
```bash
python -m venv venv
```

### 2. Ativar o ambiente
```bash
# Windows: 
venv\Scripts\activate
```
```bash
# Linux/Mac: 
source venv/bin/activate
```
### 2. Instalar as dependencias 
```bash
pip install -r requirements.txt
```

### 4. Configuração de Credenciais
1. Coloque o arquivo `serviceAccountKey.json` em `app/core/`.
2. Crie um arquivo `.env` na raiz do projeto utilize o arquivo `.env.example` como base.
3. Dentro do `.env`, adicione:
 ```
   FIREBASE_CREDENTIALS_PATH=app/core/serviceAccountKey.json
   FIREBASE_WEB_API_KEY=seu_api_key_do_firebase_aqui
   MERCADO_PAGO_ACCESS_TOKEN=TEST-seu-token-de-teste-do-mercado-pago-aqui
```
### 5. Rodar o Servidor
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

O servidor estará rodando em: http://localhost:8000

### 📂 Estrutura de Pastas
app/main.py: Onde o servidor "nasce" e as rotas são registradas.

app/routes/: Onde criamos os caminhos da API (ex: /usuarios).

app/models/: Onde definimos quais campos cada dado deve ter (Schemas).

app/core/: Configurações de conexão (Firebase).

## 📱 Como conectar o Retrofit à API do Vallet

Este tutorial explica como configurar o Retrofit no Android Studio para conectar o aplicativo Vallet à API FastAPI executada no computador.

- Se estiver usando um celular físico, conecte o computador e o celular à mesma rede Wi-Fi.

- Mantenha a API em execução na porta 8000.

- Não utilize localhost ou 127.0.0.1 para conectar um celular físico ao computador.

### 1. 🔍 Descubra o endereço IP do computador
 ```
 ipconfig
 ```
Localize o adaptador de rede utilizado e procure o campo `Endereço IPv4`.

   Endereço IPv4: `192.000.000.000`

Copie o endereço IP encontrado. O valor acima é apenas um exemplo.

### 2. 📂 Abra o arquivo RetrofitClient.kt
`app/src/main/java/br/edu/fatecpg/valletprojeto/service/RetrofitClient.kt`

Esse arquivo Kotlin configura as conexões Retrofit utilizadas pelo aplicativo.

Dentro de RetrofitClient.kt, localize a configuração valletRetrofit:
 ```
val valletRetrofit: Retrofit = Retrofit.Builder()
    .baseUrl("http://SEU-ENDERECO-IP:8000/")
    .addConverterFactory(GsonConverterFactory.create())
    .build()
```
Substitua o IP pelo endereço IPv4 do seu computador.

*Importante: mantenha `http:// no início, :8000 indicando a porta da API e a /` no final da URL.*

Não altere a URL do ViaCEP, pois ela é independente da API do Vallet.

### 4. 🚀 Execute a API FastAPI

No terminal, dentro da pasta raiz do backend, execute:

`python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
