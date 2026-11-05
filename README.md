# valletAPI
API desenvolvida para conectar aplicações de diferentes plataformas com o banco de dados

## 🛠️ Pré-requisitos
1. Ter o **Python 3.10+** instalado.
2. Ter o **VS Code** instalado.

## 🏃 Como rodar o projeto

Abra o terminal na pasta do projeto e siga estes passos:

### 1. Criar o ambiente virtual
```bash
python -m venv venv
```

### 2. Ativar o ambiente
```bash
# Windows: 
venv\Scripts\activate
# Linux/Mac: 
source venv/bin/activate
```

### 3. Instalar as bibliotecas
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

### 6. Índices do Firestore
As consultas ordenadas de notificações e a soma de receita do dashboard usam
índices compostos definidos em `firestore.indexes.json`. Para criá-los no
projeto Firebase:

```bash
firebase deploy --only firestore:indexes
```

Sem os índices, a API continua funcionando com consultas de fallback, porém
com mais leituras do Firestore.

### 📂 Estrutura de Pastas
app/main.py: Onde o servidor "nasce" e as rotas são registradas.

app/routes/: Onde criamos os caminhos da API (ex: /usuarios).

app/models/: Onde definimos quais campos cada dado deve ter (Schemas).

app/core/: Configurações de conexão (Firebase).

📖 Documentação Automática
Com o servidor rodando, acesse: http://localhost:8000/docs para ver e testar todas as rotas criadas.

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