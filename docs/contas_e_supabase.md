# Contas de usuário com Supabase (passo a passo)

Cada pessoa **pede** uma conta (usuário e senha) e **só entra depois que um administrador autorizar** no painel *Administração*. Cada conta tem os próprios dados: banca, perda máxima por trade, metas do dia, ativo e tempo gráfico,
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
ADMIN_USER = "seu_usuario"                 # admin principal: existe só nos Secrets
ADMIN_PASSWORD = "uma-senha-forte-so-sua"
SIGNUP_CODE = "um-codigo-de-convite"       # opcional: filtra pedidos de estranhos
AUTH_SECRET = "texto-longo-e-aleatorio"    # assina o link de "manter conectado"
OPENROUTER_API_KEY = "sk-or-v1-..."        # opcional: IA compartilhada (paga por você)
# LEGACY_OWNER = "seu_usuario"             # opcional: quem herda os dados de antes das contas
```
Depois use **Reboot app**. Se mudar `AUTH_SECRET`, todos os links de "manter conectado" deixam de valer.

## 3. Primeiro acesso e administração
* **Você (admin):** entre na aba **Entrar** com `ADMIN_USER` e `ADMIN_PASSWORD`. Não há cadastro para esse nome, então ninguém consegue "tomá-lo".
  Se você já usava o app antes, ponha o mesmo nome em `LEGACY_OWNER`: no primeiro login os dados antigos (configurações, carteira, extrato, log)
  são copiados para a sua conta, uma única vez.
* **Quem quer acesso:** aba **Pedir conta** (usuário, senha, o nome da pessoa e, se você definiu, o código). O pedido fica **pendente**: a senha
  certa não basta, aparece "ainda não foi autorizada".
* **Painel Administração** (menu lateral, só para admins; o menu mostra "⏳ N pedidos aguardando"):
  * **Autorizar** ou **Recusar** pedidos (recusar apaga o pedido);
  * **Bloquear** e **Reativar** contas (vale em até 1 minuto, inclusive para quem já está conectado);
  * **Excluir** a conta, com a opção de apagar também os dados dela (carteira, extrato, configurações);
  * **Senha provisória**: defina uma nova senha para quem esqueceu e informe por um canal seguro;
  * **Tornar admin** / remover admin de outras contas (o admin principal, dos Secrets, não pode ser alterado por ali).
* Quando todos tiverem conta, `ALLOW_SIGNUP = "false"` fecha os pedidos novos.
* Em **Minha conta** cada pessoa vê o resumo das escolhas salvas, troca a senha e faz backup/restauração dos próprios dados.

## Chave da Binance de cada usuário e IA do dono
* **A IA é sua**: `OPENROUTER_API_KEY` nos Secrets vale para todos, e quem usa a plataforma não vê nem informa chave de IA. Como você paga as
  chamadas, existe um limite diário **por usuário**: `AI_DAILY_LIMIT` (padrão 300 análises por dia, `0` = sem limite). Ao estourar, o bot
  continua só com as regras até o dia seguinte (00:00 UTC). Cada pessoa vê o uso em *Minha conta*.
* **A chave da Binance é de cada pessoa**: ela cadastra em *Minha conta → Conexão com a Binance* (ou na tela inicial, se você definir
  `REQUIRE_BINANCE_KEYS = "true"`; admins ficam de fora dessa exigência).
  * Fica **criptografada** (Fernet, com uma chave diferente por usuário derivada de `SECRETS_KEY`). `SECRETS_KEY` fica só nos Secrets, nunca no
    banco: quem tiver acesso apenas ao Supabase não consegue ler as chaves. **Guarde uma cópia da `SECRETS_KEY` e não a troque**: trocá-la
    torna ilegíveis as chaves já salvas (as pessoas teriam que cadastrar de novo).
  * Na tela só aparecem os 4 últimos caracteres da API Key; o Secret nunca é mostrado de volta, nem entra em backup/exportação, e some junto
    quando a conta é excluída.
  * Na hora de salvar o app confere a chave na Binance. Chaves com permissão de **saque** são **recusadas**; recomenda-se só Leitura + Trade
    e restrição por IP. Chaves de testnet também são aceitas.
  * Limite honesto: o Streamlit Community roda em servidores nos EUA e a Binance bloqueia essa região. Nesse caso a chave **não pode ser
    conferida** e a pessoa precisa marcar "Salvar mesmo se não for possível validar". O mesmo bloqueio vale para executar ordens reais a
    partir dali: a execução real exigirá um servidor em região permitida (o `worker.py`).
  * **Hoje as ordens continuam simuladas**: a chave fica guardada para quando a execução real existir. Você, como dono, tecnicamente tem
    acesso à `SECRETS_KEY` e ao banco, então consegue decifrar: avise os usuários e peça chaves sem permissão de saque.

## Se o app não pedir login
1. Os Secrets precisam estar **no topo do arquivo**, antes de qualquer linha `[secao]` (chaves abaixo de um `[título]` viram uma tabela e não são lidas).
2. Depois de editar os Secrets use **Reboot app**; o app também precisa estar na versão mais recente do branch.
3. Sem `AUTH_MODE`, o app liga as contas sozinho se houver `DATABASE_URL` e não houver `APP_PASSWORD`. Para deixar aberto de propósito, use `AUTH_MODE = "aberto"`.
4. Sem nenhum Secret de acesso, o Painel mostra "🔓 Acesso aberto" no rodapé.

## 4. Como funciona e limites
* **Senhas**: só o hash (scrypt com sal) é guardado; nunca a senha. Após 5 tentativas erradas a conta bloqueia por 5 minutos. A mensagem de erro
  não revela se o usuário existe.
* **Manter conectado**: coloca um link assinado (14 dias) na barra de endereço; quem tiver esse link entra na conta, então não o compartilhe.
  Trocar a senha invalida os links antigos. Desmarque a opção em computador compartilhado.
* **Esqueci a senha**: não há e-mail; use a senha provisória no painel Administração. Se a senha do admin principal for perdida, troque `ADMIN_PASSWORD` nos Secrets.
* **Chave da IA**: a do Secrets vale para todos. Quem não tiver chave nos Secrets informa a própria na aba IA (fica só na sessão, não é salva).
* **GitHub como armazenamento não serve para contas** (o branch pode ser público e exporia os hashes): o app recusa o login nesse modo.
* **Piloto automático** continua rodando só com a página aberta. Para rodar sem navegador, use `python worker.py` num servidor com as mesmas
  variáveis (`DATABASE_URL`, `AUTH_MODE=contas`): ele percorre todos os usuários (ou `--users ana bruno`).
* Aqui tudo é simulado (nenhum dinheiro real), mas são dados pessoais: use senha forte e mantenha o app privado se possível.
