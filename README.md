# 📊 TradeBot — Plataforma de Bots de Trade (Streamlit + DeepSeek)

Plataforma com três bots independentes (só cripto: futuros e spot), **dados de mercado reais** e **conta simulada** (paper trading),
pronta para receber a API de negociação da Binance numa segunda fase.

| Bot | Mercado | Timeframes | Padrões |
|---|---|---|---|
| ⚡ Day Trade | Futuros perpétuos USDⓈ-M (long/short) | 1m – 1h | 15m, 5× alavancado |
| 🌊 Swing Trade | Spot | 15m – 1d | 4h, sem alavancagem (opcional até 10×) |
| 🏔️ Long Trade | Spot | 4h – 1M | 1d, sem alavancagem (opcional até 10×) |

## Recursos de cada página

* **Gráfico em tempo real**: o navegador recebe os candles por WebSocket direto da corretora (Binance →
  espelho público da Binance → OKX), então cada negociação move o candle, com contagem regressiva para o
  fechamento, **lucro/prejuízo das posições mudando a cada negociação** (líquido de taxas), indicadores
  recalculados ao vivo (EMAs, Bollinger, VWAP, SuperTrend, volume e painéis de RSI, MACD, Estocástico, ADX e
  OBV) e linhas de stop, alvo, liquidação, plano da IA, suportes/resistências, pivôs, Fibonacci e níveis do usuário.
* **Seletor “Indicadores no gráfico”** acima dos gráficos para adicionar/remover indicadores na hora.
* **Dois gráficos por página**: ⚡ Tempo real e 🖊️ TradingView, com o conjunto completo de ferramentas de desenho
  (Fibonacci, canais, padrões, régua, posição comprada/vendida).
* **Boleta de entrada logo abaixo do gráfico**: à esquerda, as configurações de entrada do bot no mercado (perda máxima
  por trade em USDT ou %, stop/alvo em ATR, alavancagem e modo de margem, short); à direita, a sua ordem manual com
  calculadora (tamanho pela perda máxima ou pela margem, R:R, taxas, break-even, liquidação).
* **Conta de operação** (barra lateral): 🧪 conta demo da plataforma (simulada), 🔶 conta demo da Exchange (Binance
  testnet) ou 🔴 conta real da Exchange. As contas da Exchange exigem a chave da Binance cadastrada em Minha conta e,
  nesta versão, **ainda não recebem ordens** (o app avisa em vez de simular em silêncio).
* **Bot automático no fechamento do candle**: a IA e os bots monitoram cada candle fechado, no tempo gráfico em uso, e
  entra o bot do **ranking** com melhor desempenho no contexto atual (tempo gráfico, indicadores e leitura de mercado).
  Se nenhum tem vantagem comprovada no contexto, o bot aguarda. O ranking é **refeito sozinho a cada 7 dias**
  (`core/ranking.py`) simulando todos os bots nos candles recentes — assim acompanha o mercado real e o selo
  (aprovado / ressalva / fraco) se adapta. Também dá para atualizar na hora.
* **Varredura automática** (`core/scanner.py`): com o bot ligado, a cada candle fechado ele sorteia **20 moedas ou mais** entre as de
  maior volume do mercado da página (futuros ou spot), analisa os **últimos 120 candles fechados** de cada uma no tempo gráfico atual,
  escolhe o melhor bot do ranking para o contexto dela e opera as melhores oportunidades. Uma posição por moeda: sinal contrário
  encerra a posição em vez de abrir a oposta. A IA só é consultada para a melhor oportunidade de cada varredura e lê **todos** os
  indicadores, estejam ou não ligados no gráfico.
* **Tudo automático**: não há botões para trocar de bot, armar/desarmar plano ou analisar na mão; o ranking semanal é acompanhado
  (e pode ser forçado) na página Personalidades.
* **Papel da IA**: por padrão a IA só **explica resumidamente** o que acontece no mercado e dá uma **dica útil** do
  contexto, no tom da personalidade escolhida (professor, direto ao ponto, gestor cauteloso, mentor ou quant).
  Opcionalmente ela também **interfere** na ativação do bot: confirma ou veta o sinal naquele momento.
* **Sem bloqueios por metas**: não há meta de operações, meta de lucro, limite de perda, máximo de posições, R:R mínimo
  nem confiança mínima. O tamanho da ordem vem da perda máxima por trade e do stop; só é barrado o que é impossível
  (sem stop, venda a descoberto sem margem, alavancagem acima do máximo da Binance, quantidade zero).
* **Piloto automático** (a cada candle fechado) e execução automática opcional.
* **Carteira simulada** (página 💰 Carteira): você define a banca inicial, faz aportes/retiradas e opera
  junto com os bots na mesma banca (ou bancas separadas por bot). Tudo vira histórico, extrato (taxas,
  resultados, funding), resultado diário, comparação “você × bots”, curva de banca com drawdown, valor em R$
  e exportação para Excel.
* **Alavancagem no padrão da Binance**: futuros com as faixas oficiais por par (ex.: BTC até 150×, com a
  posição máxima diminuindo conforme a alavancagem), margem isolada/cruzada, fórmula oficial de liquidação e
  funding a cada 8 h; no spot, Binance Margin (cruzada 3×, isolada 10×).
* **🤖 Bots especialistas** — galeria com 32 bots (18 especialistas nativos + clássicos + pesquisa), cada um
  com especialidade (timeframe, indicador e risco:retorno), dica rápida, **desempenho simulado com % estimada
  ao mês**, acerto, pior queda, situação na prova final (moedas inéditas) e desempenho real; filtros por
  estilo, indicador e risco:retorno, e ativação com um clique (já ajusta o timeframe testado).
* **Personalidades (estratégias)** — página 🏆 Personalidades:
  * 9 prontas: Seguidor de Tendência, Reversão à Média, Rompimento, Scalper VWAP, Momentum, Price Action,
    Ichimoku, Conservador (multi-confirmação) e Posicional Comprador;
  * crie a sua descrevendo a estratégia em texto (a IA — ou, sem chave, palavras-chave — preenche indicadores,
    pesos, direção só compra/só venda/misto, filtros e stop/alvo), dê um nome, escolha com quem compartilhar e salve;
  * **ranking** por R médio por operação (resultado ÷ risco), somando operações reais dos bots e backtests;
  * **backtest** rápido em candles reais (só regras, sem gastar tokens), individual ou de todas de uma vez.
* **Controle do bot**: botão Ligar/Desligar (piloto automático a cada candle), Analisar agora, bot automático pelo
  ranking ou escolha manual da personalidade. Funciona sem IA (somente regras) e com IA (explica o mercado).
* **Gráfico enxuto por padrão**: duas médias móveis (Day 9/21, Swing 21/50, Long 50/200) + volume; os demais
  indicadores são adicionados no seletor acima do gráfico.
* **Todos os pares em USDT** da Binance (≈900 perpétuos e ≈700 spot) com busca.
* **Posições por bot**: posições, ordens limitadas, histórico (exporta CSV), curva de patrimônio e
  log de decisões.
* **Configurações** (abaixo do gráfico): alavancagem (faixas da Binance), todos os indicadores, IA (modelo, tom,
  se pode interferir), instruções da sua estratégia, **níveis do usuário** (enviados à IA) e custos simulados.
* **Bots criados pelos usuários** podem ser compartilhados com **toda a comunidade**, com **um ou mais usuários**
  escolhidos ou ficar **só com você**. Só o dono altera ou exclui.

## Fluxo de decisão

```
Dados reais (Binance → fallback OKX)
  → 9 habilidades de programação (votos −1…+1 com pesos por estilo)
  → bot do momento: o melhor do ranking semanal para o contexto do gráfico
  → plano por regras (entrada, stop/alvo por ATR e S/R)
  → DeepSeek via OpenRouter (explica o mercado e dá a dica; opcionalmente confirma ou veta o sinal)
  → dimensionamento pela perda máxima por trade (sem bloqueios por metas)
  → conta de operação (demo da plataforma hoje; demo/real da Exchange na fase 2)
```

Sem chave da OpenRouter, o bot funciona só com as regras.

## Como executar

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # coloque sua OPENROUTER_API_KEY
streamlit run app.py
```

Execução 24/7 sem navegador (usa as mesmas configurações salvas na interface):

```bash
export OPENROUTER_API_KEY=sk-or-...
python worker.py --bots day swing long
```

Testes: `python -m pytest -q tests`

## Publicar no Streamlit Community Cloud

1. **Onde guardar os dados (para não sumirem)** — escolha uma opção:
   * **Mini banco no GitHub (mais simples):** crie um *fine-grained token* em GitHub → Settings → Developer
     settings → Fine-grained tokens, com acesso só a este repositório e permissão **Contents: Read and
     write**. Os dados vão para o arquivo `tradebot_data.json` no branch `tradebot-data` (criado sozinho),
     separado do código, então gravar não reinicia o app. O app guarda em memória e grava a cada 20 s; o
     branch mantém sempre um único commit. Em repositório público os dados ficam públicos.
   * **Postgres gratuito (mais robusto):** projeto em [neon.tech](https://neon.tech) ou Supabase; copie a
     *connection string* `postgresql://...?sslmode=require`. Indicado se for rodar também o `worker.py`.
2. Em [share.streamlit.io](https://share.streamlit.io): **Create app** → repositório, branch e arquivo
   `app.py`.
3. **Advanced settings → Secrets**, cole (veja `.streamlit/secrets.toml.example`):
   ```toml
   APP_PASSWORD = "sua-senha-forte"
   OPENROUTER_API_KEY = "sk-or-v1-..."   # com a chave aqui, o campo da barra lateral some
   # opção GitHub:
   GITHUB_DATA_REPO = "usuario/repositorio"
   GITHUB_TOKEN = "github_pat_..."
   # ou opção Postgres:
   # DATABASE_URL = "postgresql://usuario:senha@host/neondb?sslmode=require"
   ```
4. Recomendado: em **Share**, deixe o app privado (somente convidados) além da senha.
5. Para **usuários e senhas** (cada pessoa com os próprios dados), use `AUTH_MODE = "contas"` com Supabase: veja
   [docs/contas_e_supabase.md](docs/contas_e_supabase.md).

Observações:
* A barra lateral mostra onde os dados estão (GitHub, Postgres ou arquivos locais temporários).
* No modo GitHub, o app e o `worker.py` não devem gravar ao mesmo tempo (o último a gravar prevalece); para
  usar os dois juntos, prefira o Postgres.
* O Painel tem **backup/restauração** em JSON de todos os dados.
* Os servidores do Community ficam nos EUA, onde a Binance bloqueia a API: os dados do servidor (usados pela
  IA e pela conta simulada) vêm do espelho público da Binance (spot) e da OKX (futuros). O gráfico em tempo
  real conecta a partir do seu navegador, então no Brasil usa a Binance diretamente.
* O app hiberna sem acessos; o piloto automático só roda com a página aberta. Para 24/7, rode o
  `worker.py` em um servidor com o mesmo `DATABASE_URL`.
* Login: após entrar com "manter conectado", o link da página leva um token de acesso — não compartilhe
  esse link. Trocar a senha invalida os tokens.

## Estrutura

```
app.py               navegação (sidebar) e chave da IA
views/               Painel, Carteira, Personalidades e páginas dos três bots
core/data.py         candles e cotações reais (Binance/OKX, APIs públicas)
core/indicators.py   indicadores em pandas puro
core/strategy.py     14 habilidades de programação e plano por regras (com personalidade)
core/personalities.py personalidades prontas e dos usuários (compartilhamento), ranking
core/backtest.py     backtest das personalidades em candles reais (resultado em R)
core/specialists.json bots especialistas nativos (gerados pela pesquisa)
core/research_results.json resultados simulados padronizados de todas as personalidades prontas
core/ai.py           cliente OpenRouter (DeepSeek) e prompt
core/risk.py         calculadora de trade e validação do que é impossível enviar (sem metas que bloqueiam)
core/ranking.py      ranking semanal automático dos bots (simulação nos candles recentes)
core/execution.py    conta de operação: demo da plataforma, demo da Exchange ou real da Exchange
core/paper.py        corretora simulada (stops/alvos/liquidação com máximas e mínimas reais)
core/broker.py       interface de execução (PaperBroker hoje, BinanceBroker na fase 2)
core/engine.py       pipeline completo (usado pela UI e pelo worker)
core/realtime.py     gráfico em tempo real (lightweight-charts + WebSocket no navegador)
core/auth.py         senha de acesso
core/storage.py      persistência: GitHub (branch de dados), Postgres ou arquivos JSON locais
core/ui.py           componentes Streamlit
worker.py            piloto automático em segundo plano
data/                contas, configurações e logs quando não há banco (fora do Git)
```

## Fase 2 — Binance

Implementar `BinanceBroker` em `core/broker.py` (spot: `/api/v3/order` + OCO; futuros: `/fapi/v1/leverage`,
`/fapi/v1/marginType`, `/fapi/v1/order` com `STOP_MARKET`/`TAKE_PROFIT_MARKET` reduceOnly), validar na
Testnet e trocar `get_broker`; depois ligar `EXCHANGE_ORDERS_ENABLED` em `core/execution.py`. A escolha da conta
(demo/real da Exchange) e a checagem da chave já estão prontas.

> Ferramenta educacional/experimental. Nada aqui é recomendação de investimento.

> Só cripto: futuros perpétuos e spot. Forex, commodities, índices e ações foram removidos da plataforma.
