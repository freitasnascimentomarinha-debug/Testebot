# 📊 TradeBot — Plataforma de Bots de Trade (Streamlit + DeepSeek)

Plataforma com três bots independentes, **dados de mercado reais** e **conta simulada** (paper trading),
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
* **Gráfico de análise técnica** (Plotly) com candles reais, EMAs, Bollinger, VWAP, SuperTrend, Ichimoku, RSI, MACD,
  Estocástico, ADX/DMI, OBV, volume, suportes/resistências automáticos, pivôs e Fibonacci; ferramentas de
  desenho (linha, caminho, retângulo, círculo, borracha), zoom com a roda e marcação de entradas/saídas,
  stops, alvos e preço de liquidação.
* **Aba TradingView** com o conjunto completo de ferramentas de desenho (Fibonacci, canais, padrões, régua,
  posição comprada/vendida).
* **Boleta e calculadora**: tamanho pela perda máxima ou pela margem, R:R, taxas, break-even, liquidação.
* **Botão “Analisar mercado e programar ordem”**: as habilidades de programação calculam o cenário, o
  DeepSeek 4.1 Flash interpreta e devolve a ordem em JSON, e o gestor de risco aprova/bloqueia.
* **Piloto automático** (a cada candle fechado) e execução automática opcional.
* **Carteira simulada** (página 💰 Carteira): você define a banca inicial, faz aportes/retiradas e opera
  junto com os bots na mesma banca (ou bancas separadas por bot). Tudo vira histórico, extrato (taxas,
  resultados, funding), resultado diário, comparação “você × bots”, curva de banca com drawdown, valor em R$
  e exportação para Excel.
* **Alavancagem no padrão da Binance**: futuros com as faixas oficiais por par (ex.: BTC até 150×, com a
  posição máxima diminuindo conforme a alavancagem), margem isolada/cruzada, fórmula oficial de liquidação e
  funding a cada 8 h; no spot, Binance Margin (cruzada 3×, isolada 10×).
* **Todos os pares em USDT** da Binance (≈900 perpétuos e ≈700 spot) com busca.
* **Posições por bot**: posições, ordens limitadas, histórico (exporta CSV), curva de patrimônio e
  log de decisões.
* **Configurações** (abaixo do gráfico): perda máxima por trade (USDT ou %), R:R mínimo, metas de
  operações/lucro/perda diária, máx. posições, alavancagem e modo de margem, todos os indicadores, modelo da
  IA, confiança mínima, instruções da sua estratégia e **níveis do usuário** (enviados à IA).

## Fluxo de decisão

```
Dados reais (Binance → fallback OKX)
  → 9 habilidades de programação (votos −1…+1 com pesos por estilo)
  → plano por regras (entrada, stop/alvo por ATR e S/R)
  → DeepSeek via OpenRouter (JSON: decisão, entrada, stop, alvo, confiança, riscos)
  → gestor de risco (perda máx., R:R, metas diárias, liquidação, posições)
  → corretora (simulada hoje; Binance na fase 2)
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
   OPENROUTER_API_KEY = "sk-or-v1-..."
   # opção GitHub:
   GITHUB_DATA_REPO = "usuario/repositorio"
   GITHUB_TOKEN = "github_pat_..."
   # ou opção Postgres:
   # DATABASE_URL = "postgresql://usuario:senha@host/neondb?sslmode=require"
   ```
4. Recomendado: em **Share**, deixe o app privado (somente convidados) além da senha.

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
views/               Painel + páginas dos três bots
core/data.py         candles e cotações reais (Binance/OKX, APIs públicas)
core/indicators.py   indicadores em pandas puro
core/strategy.py     habilidades de programação e plano por regras
core/ai.py           cliente OpenRouter (DeepSeek) e prompt
core/risk.py         calculadora de trade e gestor de risco
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
Testnet e trocar `get_broker`. Interface, IA e gestão de risco não mudam.

> Ferramenta educacional/experimental. Nada aqui é recomendação de investimento.
