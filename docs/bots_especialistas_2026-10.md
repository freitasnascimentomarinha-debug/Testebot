# Bots especialistas — pesquisa de out/2026

## O que foi feito

21 especialidades foram definidas com regras fixas (timeframe, mercado, indicador principal e relação
risco:retorno) e otimizadas no mesmo motor de backtest do app (conferido operação por operação):

1. **Busca** (~1.600 combinações por especialidade; 8.000 nas que não acharam candidata) nos primeiros 2/3 do
   período, em BTC, ETH, SOL, BNB e XRP. Ajustados: pesos, limiar, filtros e tamanho do stop (o alvo segue o
   risco:retorno da especialidade).
2. **Validação** no último 1/3 do período, nas mesmas moedas. Aprovadas só configurações positivas nas duas
   etapas, em ≥ 3 das 5 moedas.
3. **Prova final intocada**: 5 moedas que não participaram da seleção (DOGE, ADA, LINK, AVAX, LTC).

Períodos: futuros (5m, 15m, 1h) → últimos 40 dias; swing spot 4h → 150 dias; longo prazo spot diário → ~2,4 anos.
O retorno considera **1% da banca arriscado por operação, com juros compostos**, média de 10 moedas (cada moeda
uma banca), com taxas. **≈ ao mês** = (1 + retorno do período)^(30 ÷ dias) − 1.

Situação: **✅ Aprovado** = positivo nas moedas da busca e nas inéditas, em ≥ 6 de 10 moedas;
**🟡 Ressalva** = positivo no total, mas não nas inéditas; **⚠️ Fraco** = negativo no período.

## Resultados (todos os bots prontos)

| Bot | Especialidade | Timeframe | ≈ ao mês | Período | Acerto | Pior queda | Moedas + | Situação |
|---|---|---|---|---|---|---|---|---|
| 📊 Caçador de Volume 15m | Volume + rompimento 15m · 2:1 | Futuros 15m | +6.0% | +8.1% em 40 dias | 44% | 19% | 7/10 | 🟡 Ressalva |
| 🌀 Pullback SuperTrend + Estocástico | Pullback · SuperTrend + Estocástico · 4:1 | Futuros 1h | +5.2% | +6.9% em 40 dias | 28% | 15% | 8/10 | ✅ Aprovado |
| 📈 Tendência EMA 15m | Médias móveis 15m · 3:1 | Futuros 15m | +5.1% | +6.8% em 40 dias | 42% | 10% | 9/10 | ✅ Aprovado |
| 〽️ MACD 1h | MACD 1h · 3:1 | Futuros 1h | +4.5% | +6.0% em 40 dias | 34% | 10% | 8/10 | ✅ Aprovado |
| 🎯 Tendência Equilibrada | Tendência · MACD + SuperTrend · 1,5:1 | Futuros 1h | +3.5% | +4.6% em 40 dias | 50% | 10% | 8/10 | ✅ Aprovado |
| ☁️ Ichimoku com Força | Ichimoku + ADX + volume · 4:1 | Futuros 1h | +2.6% | +3.5% em 40 dias | 26% | 10% | 6/10 | ✅ Aprovado |
| ⚖️ Momentum Moderado | Início de tendência · 1:1 | Futuros 1h | +2.6% | +3.5% em 40 dias | 60% | 6% | 7/10 | ✅ Aprovado |
| 📐 Fibonacci 1h | Retração de Fibonacci 1h · 3:1 | Futuros 1h | +2.5% | +3.4% em 40 dias | 43% | 6% | 8/10 | ✅ Aprovado |
| 📦 Rompimento de Consolidação | Rompimento de consolidação · 1,5:1 | Futuros 1h | +2.2% | +2.9% em 40 dias | 53% | 4% | 9/10 | ✅ Aprovado |
| 🎯 Sniper Bollinger 5m | Reversão 5m · Bollinger · 2:1 | Futuros 5m | +1.6% | +2.2% em 40 dias | 43% | 16% | 6/10 | 🟡 Ressalva |
| 📐 Fibonacci 15m | Retração de Fibonacci 15m · 2:1 | Futuros 15m | +1.4% | +1.8% em 40 dias | 44% | 6% | 6/10 | ✅ Aprovado |
| 🎢 Swing Bollinger 1h | Swing 1h · Bollinger · 1:1 | Spot 1h | +1.1% | +1.4% em 40 dias | 65% | 3% | 9/10 | ✅ Aprovado |
| 🚀 Swing Rompimento 4h | Swing 4h · rompimento + volume · 3:1 | Spot 4h | +0.8% | +4.2% em 150 dias | 44% | 5% | 9/10 | ✅ Aprovado |
| 🎢 Bollinger 15m | Bandas de Bollinger 15m · 1:1 | Futuros 15m | +0.8% | +1.1% em 40 dias | 57% | 13% | 7/10 | 🟡 Ressalva |
| 🎢 Bollinger 1h | Bandas de Bollinger 1h · 1:1 | Futuros 1h | +0.8% | +1.0% em 40 dias | 58% | 5% | 6/10 | 🟡 Ressalva |
| 🧭 Seguidor de Tendência | Tendência · EMAs + SuperTrend | Spot 4h | +0.6% | +3.0% em 150 dias | 39% | 5% | 9/10 | ✅ Aprovado |
| ☁️ Ichimoku | Ichimoku | Spot 4h | +0.6% | +2.9% em 150 dias | 37% | 6% | 9/10 | ✅ Aprovado |
| 🎯 RSI Precisão 15m | RSI 15m · alvo curto · 1:2 | Futuros 15m | +0.5% | +0.7% em 40 dias | 75% | 4% | 7/10 | 🟡 Ressalva |
| 📐 Swing Fibonacci 4h | Swing 4h · Fibonacci · 2:1 | Spot 4h | +0.4% | +1.8% em 150 dias | 40% | 8% | 6/10 | ✅ Aprovado |
| 💎 Swing RSI 4h | Swing 4h · RSI sobrevendido · 2:1 | Spot 4h | +0.3% | +1.7% em 150 dias | 48% | 3% | 7/10 | ✅ Aprovado |
| 🌊 Swing Médias 4h | Swing 4h · médias móveis · 3:1 | Spot 4h | +0.2% | +1.2% em 150 dias | 42% | 4% | 5/10 | 🟡 Ressalva |
| ☁️ Longo Prazo Ichimoku | Diário · Ichimoku · 4:1 | Spot 1d | +0.1% | +3.7% em 2,4 anos | 30% | 5% | 8/10 | ✅ Aprovado |
| 📐 Longo Prazo Fibonacci | Diário · Fibonacci · 3:1 | Spot 1d | +0.1% | +3.0% em 2,4 anos | 31% | 6% | 9/10 | ✅ Aprovado |
| 🏔️ Longo Prazo Tendência | Diário · médias 50/200 · 4:1 | Spot 1d | +0.0% | +1.1% em 2,4 anos | 22% | 11% | 6/10 | 🟡 Ressalva |
| 💎 Longo Prazo RSI | Diário · RSI · 2:1 | Spot 1d | +0.0% | +1.0% em 2,4 anos | 36% | 11% | 6/10 | 🟡 Ressalva |
| 🐂 Posicional Comprador | Longo prazo · só compra | Spot 1d | -0.0% | -0.3% em 2,4 anos | 27% | 6% | 5/10 | ⚠️ Fraco |
| 🛡️ Conservador (multi-confirmação) | Multi-confirmação | Spot 4h | -0.5% | -2.6% em 150 dias | 27% | 7% | 2/10 | ⚠️ Fraco |
| 🚀 Rompimento (Breakout) | Rompimento · Donchian + volume | Futuros 15m | -9.3% | -12.2% em 40 dias | 28% | 43% | 2/10 | ⚠️ Fraco |
| 📈 Momentum | Momentum · MACD + RSI | Futuros 15m | -9.6% | -12.6% em 40 dias | 33% | 40% | 2/10 | ⚠️ Fraco |
| 🧱 Price Action (Suporte/Resistência) | Price action · suporte/resistência | Futuros 15m | -17.2% | -22.3% em 40 dias | 34% | 59% | 1/10 | ⚠️ Fraco |
| 🎯 Reversão à Média | Reversão · Bollinger + RSI | Futuros 15m | -18.4% | -23.8% em 40 dias | 35% | 35% | 0/10 | ⚠️ Fraco |
| ⚡ Scalper VWAP | Scalping · VWAP | Futuros 15m | -32.5% | -40.7% em 40 dias | 33% | 63% | 0/10 | ⚠️ Fraco |

## Leituras importantes

- **Scalping em 5 minutos não funcionou**: Scalper VWAP 5m (1:1), RSI 5m (1:2) e EMA 5m (3:1) não tiveram nenhuma
  configuração consistente mesmo com 8.000 tentativas — por isso não viraram bots.
- As personalidades clássicas de day trade (Scalper VWAP, Reversão, Price Action, Momentum, Rompimento) foram
  **muito negativas no 15m** — o Scalper VWAP, antigo padrão do Day Trade, daria −40% em 40 dias. Os padrões
  agora são especialistas aprovados: Day Trade → Tendência EMA 15m, Swing → Swing Rompimento 4h,
  Longo prazo → Longo Prazo Ichimoku.
- Os bots de longo prazo rendem pouco por mês com 1% de risco por operação (poucas operações em ~2,4 anos):
  são mais úteis como filtro de entradas do que como fonte de retorno.
- Nenhum bot ganhou em todas as moedas; passado não garante futuro. Use a carteira simulada para medir o
  desempenho real antes de qualquer dinheiro real.
