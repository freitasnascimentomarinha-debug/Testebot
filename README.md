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
  fechamento e linhas de posição, stop, alvo, liquidação, plano da IA e níveis do usuário.
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
* **Conta simulada** por bot: posições, ordens limitadas, histórico (exporta CSV), curva de patrimônio e
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

1. **Banco gratuito (para os dados não sumirem)** — crie um projeto em [neon.tech](https://neon.tech) (ou
   Supabase), região São Paulo se houver, e copie a *connection string* `postgresql://...?sslmode=require`.
   A tabela `tradebot_kv` é criada sozinha no primeiro acesso.
2. Em [share.streamlit.io](https://share.streamlit.io): **Create app** → repositório, branch e arquivo
   `app.py`.
3. **Advanced settings → Secrets**, cole (veja `.streamlit/secrets.toml.example`):
   ```toml
   APP_PASSWORD = "sua-senha-forte"
   OPENROUTER_API_KEY = "sk-or-v1-..."
   DATABASE_URL = "postgresql://usuario:senha@host/neondb?sslmode=require"
   ```
4. Recomendado: em **Share**, deixe o app privado (somente convidados) além da senha.

Observações:
* A barra lateral mostra se o armazenamento está em **Postgres (permanente)** ou em arquivos locais.
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
core/storage.py      persistência: Postgres (DATABASE_URL) ou arquivos JSON locais
core/ui.py           componentes Streamlit
worker.py            piloto automático em segundo plano
data/                contas, configurações e logs quando não há banco (fora do Git)
```

## Fase 2 — Binance

Implementar `BinanceBroker` em `core/broker.py` (spot: `/api/v3/order` + OCO; futuros: `/fapi/v1/leverage`,
`/fapi/v1/marginType`, `/fapi/v1/order` com `STOP_MARKET`/`TAKE_PROFIT_MARKET` reduceOnly), validar na
Testnet e trocar `get_broker`. Interface, IA e gestão de risco não mudam.

> Ferramenta educacional/experimental. Nada aqui é recomendação de investimento.
