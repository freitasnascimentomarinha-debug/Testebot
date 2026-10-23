# Contas de usuário com Supabase (passo a passo)

Cada pessoa cria o seu **usuário e senha** e tem os próprios dados: banca, perda máxima por trade, metas do dia, ativo e tempo gráfico,
personalidade, alavancagem, carteira, extrato, log de decisões e planos armados. Tudo fica salvo no Supabase e volta igual ao entrar de
qualquer aparelho. Estratégias criadas na página Personalidades continuam compartilhadas entre todos.

## 1. Criar o banco no Supabase
1. Em [supabase.com](https://supabase.com) → **New project** (região *South America (São Paulo)*), defina a **Database Password** e guarde-a.
2. No projeto, clique em **Connect** → **Connection string** → aba **URI** → método **Session pooler** (o direto usa IPv6 e o Streamlit
   Community Cloud só tem IPv4).
3. Copie a URI e troque `[YOUR-PASSWORD]` pela senha do banco. Se ela tiver caracteres especiais, codifique na URL (`@` → `%40`, `#` → `%23`).
   Fica assim: `postgresql://postgres.abcdefgh:SENHA@aws-0-sa-east-1.pooler.supabase.com:5432/postgres`

Não é preciso criar tabela: o app cria a `tradebot_kv` sozinho e **liga o RLS** (nenhuma política), de modo que a API pública do Supabase
(chave `anon`) não consegue ler nada. O app acessa por conexão direta do banco.

## 2. Secrets no Streamlit Community Cloud
**App settings → Secrets**:
```toml
DATABASE_URL = "postgresql://postgres.abcdefgh:SENHA@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
AUTH_MODE = "contas"
SIGNUP_CODE = "um-codigo-de-convite"       # só quem tem o código cria conta
AUTH_SECRET = "texto-longo-e-aleatorio"    # assina o link de "manter conectado"
OPENROUTER_API_KEY = "sk-or-v1-..."        # opcional: IA compartilhada (paga por você)
# LEGACY_OWNER = "seu_usuario"             # opcional: quem herda os dados de antes das contas
```
Depois use **Reboot app**. Se mudar `AUTH_SECRET`, todos os links de "manter conectado" deixam de valer.

## 3. Primeiro acesso
* Abra o app → aba **Criar conta** → usuário, senha (mínimo 8 caracteres) e o código de convite.
* Se você já usava o app antes (dados na versão de uma pessoa só), crie a sua conta com o mesmo nome definido em `LEGACY_OWNER`: no primeiro
  login os dados antigos (configurações, carteira, extrato, log) são copiados para a sua conta, uma única vez.
* Depois que todos tiverem conta, coloque `ALLOW_SIGNUP = "false"` para fechar o cadastro.
* Em **Minha conta**: resumo das escolhas salvas, troca de senha e backup/restauração dos seus dados.

## 4. Como funciona e limites
* **Senhas**: só o hash (scrypt com sal) é guardado; nunca a senha. Após 5 tentativas erradas a conta bloqueia por 5 minutos. A mensagem de erro
  não revela se o usuário existe.
* **Manter conectado**: coloca um link assinado (14 dias) na barra de endereço; quem tiver esse link entra na conta, então não o compartilhe.
  Trocar a senha invalida os links antigos. Desmarque a opção em computador compartilhado.
* **Esqueci a senha**: não há recuperação por e-mail. Quem administra o banco pode apagar o usuário na tabela `tradebot_kv` (linha `_users.json`)
  para a pessoa se cadastrar de novo, ou redefinir editando o JSON.
* **Chave da IA**: a do Secrets vale para todos. Quem não tiver chave nos Secrets informa a própria na aba IA (fica só na sessão, não é salva).
* **GitHub como armazenamento não serve para contas** (o branch pode ser público e exporia os hashes): o app recusa o login nesse modo.
* **Piloto automático** continua rodando só com a página aberta. Para rodar sem navegador, use `python worker.py` num servidor com as mesmas
  variáveis (`DATABASE_URL`, `AUTH_MODE=contas`): ele percorre todos os usuários (ou `--users ana bruno`).
* Aqui tudo é simulado (nenhum dinheiro real), mas são dados pessoais: use senha forte e mantenha o app privado se possível.
