# Bots especialistas — pesquisa de out/2026

## O que foi feito

38 especialidades foram definidas (21 iniciais + 17 de 5 minutos com filtro de contexto) com regras fixas (timeframe, mercado, indicador principal e relação
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

| Bot | Especialidade | Timeframe | ≈ ao mês | Período | Acerto | Pior queda | Moedas + | Situação | Melhores contextos | Só nos favoráveis |
|---|---|---|---|---|---|---|---|---|---|---|
| 📊 Caçador de Volume 15m | Volume + rompimento 15m · 2:1 | Futuros 15m | +6.0% | +8.1% em 40 dias | 44% | 19% | 7/10 | 🟡 Ressalva | 🚀 Rompimento de alta, 📉 Tendência de baixa, ↩️ Pullback em tendência de alta | -0.2%/mês (⚠️ Fraco) |
| 🌀 Pullback SuperTrend + Estocástico | Pullback · SuperTrend + Estocástico · 4:1 | Futuros 1h | +5.2% | +6.9% em 40 dias | 28% | 15% | 8/10 | ✅ Aprovado | 📉 Tendência de baixa, ↪️ Pullback em tendência de baixa, 📈 Tendência de alta | +3.4%/mês (✅ Aprovado) |
| 📈 Tendência EMA 15m | Médias móveis 15m · 3:1 | Futuros 15m | +5.1% | +6.8% em 40 dias | 42% | 10% | 9/10 | ✅ Aprovado | ↩️ Pullback em tendência de alta, 🔄 Reversão para alta (fundo), 💥 Rompimento de baixa | +3.8%/mês (✅ Aprovado) |
| 〽️ MACD 1h | MACD 1h · 3:1 | Futuros 1h | +4.5% | +6.0% em 40 dias | 34% | 10% | 8/10 | ✅ Aprovado | 🔃 Reversão para baixa (topo), ↩️ Pullback em tendência de alta, 🚀 Rompimento de alta | +2.8%/mês (✅ Aprovado) |
| 🎯 Reversão Bollinger 5m 2:1 | Bollinger + reversão 5m · só em reversão/lateral · 2:1 | Futuros 5m | +3.7% | +4.9% em 40 dias | 54% | 5% | 8/10 | ✅ Aprovado | 🔄 Reversão para alta (fundo) | +4.1%/mês (✅ Aprovado) |
| 🎯 Tendência Equilibrada | Tendência · MACD + SuperTrend · 1,5:1 | Futuros 1h | +3.5% | +4.6% em 40 dias | 50% | 10% | 8/10 | ✅ Aprovado | 📉 Tendência de baixa, 🔄 Reversão para alta (fundo), 📈 Tendência de alta | +3.9%/mês (✅ Aprovado) |
| 🌋 Clímax de Volume 5m | Volume + reversão 5m · 1,5:1 | Futuros 5m | +3.4% | +4.5% em 40 dias | 62% | 4% | 8/10 | ✅ Aprovado | 🔄 Reversão para alta (fundo) | +3.4%/mês (✅ Aprovado) |
| 🧱 Reação em Suporte 5m | Suporte/resistência + reversão 5m · 1,5:1 | Futuros 5m | +3.1% | +4.1% em 40 dias | 59% | 7% | 7/10 | ✅ Aprovado | 🔄 Reversão para alta (fundo) | +3.1%/mês (✅ Aprovado) |
| ☁️ Ichimoku com Força | Ichimoku + ADX + volume · 4:1 | Futuros 1h | +2.6% | +3.5% em 40 dias | 26% | 10% | 6/10 | ✅ Aprovado | 📉 Tendência de baixa, 📈 Tendência de alta, 💥 Rompimento de baixa | +4.3%/mês (✅ Aprovado) |
| ⚖️ Momentum Moderado | Início de tendência · 1:1 | Futuros 1h | +2.6% | +3.5% em 40 dias | 60% | 6% | 7/10 | ✅ Aprovado | ↪️ Pullback em tendência de baixa, 🔃 Reversão para baixa (topo), 🚀 Rompimento de alta | +1.3%/mês (✅ Aprovado) |
| 📐 Fibonacci 1h | Retração de Fibonacci 1h · 3:1 | Futuros 1h | +2.5% | +3.4% em 40 dias | 43% | 6% | 8/10 | ✅ Aprovado | 💥 Rompimento de baixa, ↔️ Lateralidade, ↩️ Pullback em tendência de alta | +2.5%/mês (✅ Aprovado) |
| 📦 Rompimento de Consolidação | Rompimento de consolidação · 1,5:1 | Futuros 1h | +2.2% | +2.9% em 40 dias | 53% | 4% | 9/10 | ✅ Aprovado | 🚀 Rompimento de alta | +0.8%/mês (✅ Aprovado) |
| 📐 Fibonacci Reversão 5m | Fibonacci + reversão 5m · 1,5:1 | Futuros 5m | +2.1% | +2.8% em 40 dias | 58% | 6% | 7/10 | ✅ Aprovado | 🔄 Reversão para alta (fundo) | +2.1%/mês (✅ Aprovado) |
| 🔁 Reversão Estocástico 5m | Estocástico + reversão 5m · só em reversão/lateral · 1:1 | Futuros 5m | +2.0% | +2.7% em 40 dias | 66% | 4% | 8/10 | ✅ Aprovado | 🔄 Reversão para alta (fundo), ↩️ Pullback em tendência de alta | +2.2%/mês (✅ Aprovado) |
| 🎢 Bollinger Lateral 5m | Bollinger 5m · só em lateralidade/reversão · 1:1 | Futuros 5m | +1.9% | +2.5% em 40 dias | 69% | 4% | 9/10 | ✅ Aprovado | 🔄 Reversão para alta (fundo) | +1.8%/mês (✅ Aprovado) |
| 🎯 Sniper Bollinger 5m | Reversão 5m · Bollinger · 2:1 | Futuros 5m | +1.6% | +2.2% em 40 dias | 43% | 16% | 6/10 | 🟡 Ressalva | 💥 Rompimento de baixa, ↩️ Pullback em tendência de alta, 🚀 Rompimento de alta | +0.8%/mês (🟡 Ressalva) |
| 🔄 Reversão RSI 5m | RSI + reversão 5m · só em reversão/lateral · 1:1 | Futuros 5m | +1.6% | +2.1% em 40 dias | 68% | 4% | 8/10 | ✅ Aprovado | 🔄 Reversão para alta (fundo) | +1.6%/mês (✅ Aprovado) |
| 📐 Fibonacci 15m | Retração de Fibonacci 15m · 2:1 | Futuros 15m | +1.4% | +1.8% em 40 dias | 44% | 6% | 6/10 | ✅ Aprovado | ↔️ Lateralidade, ↪️ Pullback em tendência de baixa | +1.3%/mês (🟡 Ressalva) |
| 🎢 Swing Bollinger 1h | Swing 1h · Bollinger · 1:1 | Spot 1h | +1.1% | +1.4% em 40 dias | 65% | 3% | 9/10 | ✅ Aprovado | 🚀 Rompimento de alta | +0.4%/mês (🟡 Ressalva) |
| 🚀 Swing Rompimento 4h | Swing 4h · rompimento + volume · 3:1 | Spot 4h | +0.8% | +4.2% em 150 dias | 44% | 5% | 9/10 | ✅ Aprovado | 🔃 Reversão para baixa (topo), 🚀 Rompimento de alta, 📈 Tendência de alta | +0.9%/mês (✅ Aprovado) |
| 🎢 Bollinger 15m | Bandas de Bollinger 15m · 1:1 | Futuros 15m | +0.8% | +1.1% em 40 dias | 57% | 13% | 7/10 | 🟡 Ressalva | 🔄 Reversão para alta (fundo), 💥 Rompimento de baixa | +0.5%/mês (🟡 Ressalva) |
| 🎢 Bollinger 1h | Bandas de Bollinger 1h · 1:1 | Futuros 1h | +0.8% | +1.0% em 40 dias | 58% | 5% | 6/10 | 🟡 Ressalva | 🚀 Rompimento de alta, ↩️ Pullback em tendência de alta, 📈 Tendência de alta | -0.4%/mês (⚠️ Fraco) |
| 🧭 Seguidor de Tendência | Tendência · EMAs + SuperTrend | Spot 4h | +0.6% | +3.0% em 150 dias | 39% | 5% | 9/10 | ✅ Aprovado | 🔃 Reversão para baixa (topo), 🚀 Rompimento de alta, 📈 Tendência de alta | +0.8%/mês (✅ Aprovado) |
| ☁️ Ichimoku | Ichimoku | Spot 4h | +0.6% | +2.9% em 150 dias | 37% | 6% | 9/10 | ✅ Aprovado | 🔃 Reversão para baixa (topo), 📈 Tendência de alta, 🚀 Rompimento de alta | +0.8%/mês (✅ Aprovado) |
| 🎯 RSI Precisão 15m | RSI 15m · alvo curto · 1:2 | Futuros 15m | +0.5% | +0.7% em 40 dias | 75% | 4% | 7/10 | 🟡 Ressalva | 💥 Rompimento de baixa, 📉 Tendência de baixa | -0.1%/mês (⚠️ Fraco) |
| 📐 Swing Fibonacci 4h | Swing 4h · Fibonacci · 2:1 | Spot 4h | +0.4% | +1.8% em 150 dias | 40% | 8% | 6/10 | ✅ Aprovado | 🔃 Reversão para baixa (topo), 🚀 Rompimento de alta, 📉 Tendência de baixa | +0.7%/mês (✅ Aprovado) |
| 💎 Swing RSI 4h | Swing 4h · RSI sobrevendido · 2:1 | Spot 4h | +0.3% | +1.7% em 150 dias | 48% | 3% | 7/10 | ✅ Aprovado | 💥 Rompimento de baixa | +0.2%/mês (✅ Aprovado) |
| 🌊 Swing Médias 4h | Swing 4h · médias móveis · 3:1 | Spot 4h | +0.2% | +1.2% em 150 dias | 42% | 4% | 5/10 | 🟡 Ressalva | 🔃 Reversão para baixa (topo), 🚀 Rompimento de alta, ↩️ Pullback em tendência de alta | +0.2%/mês (✅ Aprovado) |
| ☁️ Longo Prazo Ichimoku | Diário · Ichimoku · 4:1 | Spot 1d | +0.1% | +3.7% em 2,4 anos | 30% | 5% | 8/10 | ✅ Aprovado | 🚀 Rompimento de alta, ↔️ Lateralidade | +0.1%/mês (✅ Aprovado) |
| 📐 Longo Prazo Fibonacci | Diário · Fibonacci · 3:1 | Spot 1d | +0.1% | +3.0% em 2,4 anos | 31% | 6% | 9/10 | ✅ Aprovado | 🚀 Rompimento de alta, 💥 Rompimento de baixa, ↔️ Lateralidade | +0.2%/mês (✅ Aprovado) |
| 🏔️ Longo Prazo Tendência | Diário · médias 50/200 · 4:1 | Spot 1d | +0.0% | +1.1% em 2,4 anos | 22% | 11% | 6/10 | 🟡 Ressalva | 🔃 Reversão para baixa (topo), 🚀 Rompimento de alta, ↔️ Lateralidade | +0.1%/mês (🟡 Ressalva) |
| 💎 Longo Prazo RSI | Diário · RSI · 2:1 | Spot 1d | +0.0% | +1.0% em 2,4 anos | 36% | 11% | 6/10 | 🟡 Ressalva | 🔃 Reversão para baixa (topo), 🚀 Rompimento de alta, ↔️ Lateralidade | +0.1%/mês (✅ Aprovado) |
| 🐂 Posicional Comprador | Longo prazo · só compra | Spot 1d | -0.0% | -0.3% em 2,4 anos | 27% | 6% | 5/10 | ⚠️ Fraco | 🔃 Reversão para baixa (topo), 🚀 Rompimento de alta, ↔️ Lateralidade | +0.0%/mês (✅ Aprovado) |
| 🛡️ Conservador (multi-confirmação) | Multi-confirmação | Spot 4h | -0.5% | -2.6% em 150 dias | 27% | 7% | 2/10 | ⚠️ Fraco | — | — |
| 🚀 Rompimento (Breakout) | Rompimento · Donchian + volume | Futuros 15m | -9.3% | -12.2% em 40 dias | 28% | 43% | 2/10 | ⚠️ Fraco | ↩️ Pullback em tendência de alta, 🔄 Reversão para alta (fundo), 📈 Tendência de alta | -1.6%/mês (⚠️ Fraco) |
| 📈 Momentum | Momentum · MACD + RSI | Futuros 15m | -9.6% | -12.6% em 40 dias | 33% | 40% | 2/10 | ⚠️ Fraco | — | — |
| 🧱 Price Action (Suporte/Resistência) | Price action · suporte/resistência | Futuros 15m | -17.2% | -22.3% em 40 dias | 34% | 59% | 1/10 | ⚠️ Fraco | — | — |
| 🎯 Reversão à Média | Reversão · Bollinger + RSI | Futuros 15m | -18.4% | -23.8% em 40 dias | 35% | 35% | 0/10 | ⚠️ Fraco | — | — |
| ⚡ Scalper VWAP | Scalping · VWAP | Futuros 15m | -32.5% | -40.7% em 40 dias | 33% | 63% | 0/10 | ⚠️ Fraco | — | — |

## Desempenho por contexto do gráfico

Cada candle é classificado (core/regime.py) em um contexto **somente quando há sinal claro**: rompimento,
reversão, pullback, tendência de alta/baixa ou lateralidade (o resto fica "sem sinal claro"). Cada bot foi
simulado operando **apenas** em cada contexto. Os contextos favoráveis de cada bot foram escolhidos nas moedas da
busca e testados nas moedas inéditas.

| Contexto | Quando acontece | Melhores bots (R médio por operação só nesse contexto) |
|---|---|---|
| 🚀 Rompimento de alta | Fechou acima da máxima de 20 candles com volume ≥ 1,5× a média. | 📐 Longo Prazo Fibonacci (1d) +1.28R; ☁️ Longo Prazo Ichimoku (1d) +0.69R; 🚀 Swing Rompimento 4h (4h) +0.59R |
| 💥 Rompimento de baixa | Fechou abaixo da mínima de 20 candles com volume ≥ 1,5× a média. | 📐 Fibonacci 1h (1h) +0.76R; 📐 Longo Prazo Fibonacci (1d) +0.47R; 📐 Swing Fibonacci 4h (4h) +0.39R |
| 🔄 Reversão para alta (fundo) | RSI ≤ 30 com o preço tocando a banda inferior de Bollinger. | 🎯 Reversão Bollinger 5m 2:1 (5m) +0.40R; 🌋 Clímax de Volume 5m (5m) +0.32R; 📈 Tendência EMA 15m (15m) +0.30R |
| 🔃 Reversão para baixa (topo) | RSI ≥ 70 com o preço tocando a banda superior de Bollinger. | 📐 Swing Fibonacci 4h (4h) +0.99R; 🚀 Swing Rompimento 4h (4h) +0.92R; 🏔️ Longo Prazo Tendência (1d) +0.91R |
| ↩️ Pullback em tendência de alta | Tendência de alta (EMA lenta > EMA 200) com recuo abaixo da EMA rápida e RSI 35–55. | 〽️ MACD 1h (1h) +0.72R; 📐 Fibonacci 1h (1h) +0.47R; 📈 Tendência EMA 15m (15m) +0.41R |
| ↪️ Pullback em tendência de baixa | Tendência de baixa (EMA lenta < EMA 200) com repique acima da EMA rápida e RSI 45–65. | 🎯 Reversão Bollinger 5m 2:1 (5m) +0.28R; 📐 Fibonacci 1h (1h) +0.25R; ⚖️ Momentum Moderado (1h) +0.15R |
| 📈 Tendência de alta | ADX ≥ 25, +DI > −DI e preço > EMA lenta > EMA 200. | 🚀 Swing Rompimento 4h (4h) +0.47R; 〽️ MACD 1h (1h) +0.31R; ☁️ Ichimoku (4h) +0.29R |
| 📉 Tendência de baixa | ADX ≥ 25, −DI > +DI e preço < EMA lenta < EMA 200. | 🎯 Tendência Equilibrada (1h) +0.42R; ☁️ Ichimoku com Força (1h) +0.31R; 📐 Swing Fibonacci 4h (4h) +0.28R |
| ↔️ Lateralidade | ADX < 18 e Bandas de Bollinger mais estreitas que o normal. | 📐 Fibonacci 1h (1h) +0.69R; 📐 Longo Prazo Fibonacci (1d) +0.58R; 🔁 Reversão Estocástico 5m (5m) +0.43R |

## Leituras importantes

- **5 minutos**: seguir tendência não funcionou (scalper VWAP, médias, MACD, SuperTrend, Ichimoku e rompimento em
  5m não passaram). O que funcionou foi **operar exaustão**: comprar fundos de capitulação (contexto "Reversão
  para alta") e a lateralidade — 7 bots de 5m aprovados, com acerto de 54% a 69% e quedas de 4% a 7%. Atenção: eles
  exploram a **mesma vantagem** (reversão após queda forte), então se movem juntos — não diversificam entre si.
- **Filtro de contexto** ajuda vários bots (Ichimoku com Força, Tendência Equilibrada, Swing Fibonacci 4h,
  Longo Prazo Fibonacci) e piora outros (Caçador de Volume 15m). O card mostra quando vale ligar.
- As personalidades clássicas de day trade foram muito negativas no 15m. Os padrões agora são especialistas
  aprovados: Day Trade → Tendência EMA 15m, Swing → Swing Rompimento 4h, Longo prazo → Longo Prazo Ichimoku.
- Longo prazo rende pouco por mês com 1% de risco por operação (poucas operações em ~2,4 anos).
- Nenhum bot ganhou em todas as moedas; passado não garante futuro. Use a carteira simulada para medir o real.
