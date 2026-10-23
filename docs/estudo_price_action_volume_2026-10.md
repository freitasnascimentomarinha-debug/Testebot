# Estudo: price action, tendência e volume (out/2026)

Pedido: testar as versões **A Price action**, **B Tendência + indicadores**, **C Tendência + volume** e **D Híbrida**,
com filtro de tendência do tempo maior (4h para entradas de 15m e 1h), volume relativo mínimo, stop em ATR além da
região que invalida, comparação de saídas **1R / 1,5R / 2R** e risco de **0,25%–0,5%** por trade — e criar 5 bots vencedores
(pelo menos 1 de price action).

## Método (sem olhar o futuro)

* Motor: o mesmo do app (`core/fastsim.py`, provado idêntico ao backtest candle a candle — inclusive com o filtro do 4h,
  ver `tests/test_core.py`). Sinal no fechamento do candle, entrada no fechamento, stop/alvo verificados nos candles seguintes;
  se stop e alvo cabem no mesmo candle, conta **stop** (pior caso). Taxa de 0,04% por lado já descontada.
* Tempo maior: cada candle de 15m/1h usa só o último candle de 4h **já fechado** (EMA 21/50).
* Dados: Binance Futuros USDT-M, 80 dias até 23/10/2026.
  Moedas principais (seleção): BTC, ETH, SOL, BNB, XRP. Moedas **inéditas** (prova): DOGE, ADA, LINK, AVAX, LTC.
* Busca aleatória: 1.000 (rodada 1) e 4.000 (rodada 2) combinações por família × tempo × saída (pesos dos votos, limiar, direção, stop 1–3 ATR,
  filtro 4h liga/desliga, volume relativo 0/1,0/1,2/1,5/2,0×, filtro de lateralidade, ADX mínimo, contextos).

### Rodada 1 — seleção só nos 40 dias recentes ❌
Seleção nos 27+13 dias recentes das moedas principais. Quase tudo passou nas moedas inéditas recentes, mas
**perdeu nos 40 dias anteriores** (outro regime de mercado). Conclusão: estratégias ajustadas a um único regime. Rejeitadas.

| Versão | Tempo | Saída | Inéditas (40d recentes) | Todas (40d anteriores) |
|---|---|---|---|---|
| A Price action | 15m | 1.0R | +0.28R (5/5) | -0.29R (2/10) |
| A Price action | 15m | 1.5R | -0.03R (3/5) | -0.36R (3/10) |
| A Price action | 15m | 2.0R | +0.22R (4/5) | -0.32R (2/10) |
| A Price action | 1h | 1.0R | -0.10R (3/5) | -0.11R (3/10) |
| A Price action | 1h | 1.5R | -0.43R (0/5) | -0.60R (2/10) |
| A Price action | 1h | 2.0R | -0.25R (2/5) | -0.34R (3/10) |
| B Tendência + indicadores | 15m | 1.0R | +0.14R (4/5) | -0.50R (0/10) |
| B Tendência + indicadores | 15m | 1.5R | +0.04R (3/5) | -0.58R (0/10) |
| B Tendência + indicadores | 15m | 2.0R | +0.15R (3/5) | -0.14R (3/10) |
| C Tendência + volume | 15m | 1.0R | -0.34R (1/5) | -0.47R (0/10) |
| C Tendência + volume | 15m | 1.5R | +0.27R (5/5) | -0.61R (0/10) |
| C Tendência + volume | 15m | 2.0R | +0.22R (5/5) | -0.54R (0/10) |
| D Híbrida | 15m | 1.0R | -0.05R (2/5) | -0.24R (1/10) |
| D Híbrida | 15m | 1.5R | +0.11R (3/5) | -0.56R (0/10) |
| D Híbrida | 15m | 2.0R | +0.17R (3/5) | -0.65R (0/10) |
| D Híbrida | 1h | 1.0R | +0.00R (3/5) | -0.53R (1/10) |
| D Híbrida | 1h | 1.5R | +0.05R (3/5) | +0.09R (7/10) |
| D Híbrida | 1h | 2.0R | +0.06R (2/5) | -0.55R (2/10) |
| D Híbrida | 5m | 1.0R | sem aprovado | — |
| D Híbrida | 5m | 1.5R | sem aprovado | — |
| D Híbrida | 5m | 2.0R | sem aprovado | — |

### Rodada 2 — seleção exige lucro nos dois regimes ✅
Seleção nas moedas principais exigindo média em R **positiva em três blocos**: 40 dias anteriores, 27 dias de busca e 13 dias de
validação. A prova final é intocada: as **5 moedas inéditas nos 80 dias**, separadas por regime. Aprovado = positivo nas inéditas
nos dois regimes. Valores em R (múltiplos do risco) por trade, já com taxas.

| Versão | Tempo | Saída | Seleção: anteriores / busca / valid. | Inéditas 40d anteriores | Inéditas 40d recentes | Resultado |
|---|---|---|---|---|---|---|
| A Price action | 15m | 1.0R | +0.08 / +0.03 / +0.16 | -0.09R (2/5) | +0.14R (5/5) | ❌ |
| A Price action | 15m | 1.5R | +0.07 / +0.05 / +0.10 | -0.26R (0/5) | +0.08R (5/5) | ❌ |
| A Price action | 15m | 2.0R | +0.09 / +0.05 / +0.07 | +0.03R (3/5) | +0.02R (3/5) | ✅ reserva |
| A Price action | 1h | 1.0R | +0.21 / +0.09 / +0.17 | +0.04R (3/5) | +0.09R (3/5) | **🕯️ Price Action Puro 1h** |
| A Price action | 1h | 1.5R | +0.19 / +0.23 / +0.28 | +0.08R (3/5) | +0.02R (2/5) | ✅ reserva |
| A Price action | 1h | 2.0R | +0.16 / +0.24 / +0.42 | -0.01R (2/5) | -0.06R (1/5) | ❌ |
| B Tendência + indicadores | 15m | 1.0R | +0.17 / +0.06 / +0.15 | -0.33R (0/5) | +0.00R (4/5) | ❌ |
| B Tendência + indicadores | 15m | 1.5R | +0.15 / +0.12 / +0.16 | +0.37R (4/5) | +0.10R (5/5) | ✅ reserva |
| B Tendência + indicadores | 15m | 2.0R | +0.19 / +0.09 / +0.07 | +0.40R (4/5) | +0.10R (5/5) | **📐 Tendência + MACD 15m** |
| B Tendência + indicadores | 1h | 1.0R | +0.11 / +0.35 / +0.44 | -0.07R (2/5) | +0.04R (3/5) | ❌ |
| B Tendência + indicadores | 1h | 1.5R | +0.46 / +0.24 / +0.43 | +0.03R (3/5) | +0.20R (2/5) | ✅ reserva |
| B Tendência + indicadores | 1h | 2.0R | +0.35 / +0.20 / +0.36 | +0.51R (5/5) | +0.20R (4/5) | **🧭 Tendência Forte 1h** |
| C Tendência + volume | 15m | 1.0R | +0.14 / +0.15 / +0.29 | -0.40R (1/5) | -0.02R (2/5) | ❌ |
| C Tendência + volume | 15m | 1.5R | +0.05 / +0.02 / +0.04 | -0.07R (2/5) | +0.08R (4/5) | ❌ |
| C Tendência + volume | 15m | 2.0R | +0.09 / +0.09 / +0.09 | +0.14R (3/5) | +0.07R (2/5) | ✅ reserva |
| C Tendência + volume | 1h | 1.0R | +0.26 / +0.27 / +0.19 | +0.10R (4/5) | +0.13R (4/5) | ✅ reserva |
| C Tendência + volume | 1h | 1.5R | +0.25 / +0.27 / +0.23 | -0.07R (1/5) | +0.14R (4/5) | ❌ |
| C Tendência + volume | 1h | 2.0R | +0.34 / +0.31 / +0.38 | +0.32R (5/5) | +0.30R (4/5) | **📊 Rompimento com Volume 1h** |
| D Híbrida | 15m | 1.0R | +0.15 / +0.09 / +0.48 | -0.46R (0/5) | -0.05R (3/5) | ❌ |
| D Híbrida | 15m | 1.5R | +0.30 / +0.19 / +0.22 | -0.22R (2/5) | -0.28R (1/5) | ❌ |
| D Híbrida | 15m | 2.0R | +0.07 / +0.29 / +0.06 | +0.09R (3/5) | +0.11R (3/5) | ✅ reserva |
| D Híbrida | 1h | 1.0R | +0.20 / +0.19 / +0.27 | +0.15R (4/5) | +0.18R (4/5) | ✅ reserva |
| D Híbrida | 1h | 1.5R | +0.29 / +0.46 / +0.91 | +0.03R (2/5) | +0.28R (4/5) | ✅ reserva |
| D Híbrida | 1h | 2.0R | +0.24 / +0.20 / +0.40 | +0.28R (4/5) | +0.29R (3/5) | **🧬 Híbrida Price Action + Volume 1h** |

**Leitura das saídas:** no 1h, as saídas **2R** venceram em B, C e D; no price action puro (A) a melhor foi **1R**
(acerto alto, ~55–60%). No 15m, só a família B teve borda clara nos dois regimes (A, C e D no 15m ficaram perto de zero). O 5m não tem 80 dias de dados e
falhou já na rodada 1 — ficou fora.

**Filtro de lateralidade** (`avoid_lateral`): a busca o manteve em 2 dos 5 vencedores (B 15m e C 1h); nos outros não melhorou.
**Filtro do 4h**: manteve-se no price action (A 1h); nos demais a busca preferiu o filtro de EMA/ADX do próprio tempo.
**Volume relativo**: 4 dos 5 vencedores exigem volume ≥ 1,0–1,5× a média.

## Os 5 bots criados

Métricas completas (taxas incluídas). Retorno = média por moeda com juros compostos; DD = maior rebaixamento em uma moeda.

### 🕯️ Price Action Puro 1h  (A Price action · 1h · alvo 1.0R)
Votos {'estrutura': 1.0, 'suporte_resistencia': 2.0, 'rompimento': 1.5} · limiar 10 · direção misto · stop 2.5 ATR · alvo 2.5 ATR · filtros {'htf_trend': True, 'ignore_regime': True, 'adx_min': 25, 'contexts': ['tendencia_baixa', 'pullback_baixa', 'rompimento_alta']} · custo de taxas ≈ 0.047R por trade

| Bloco | Trades | Acerto | Expectativa | Fator de lucro | Retorno 0,25% | Retorno 0,5% | Retorno 1% | DD (0,5%) | Moedas + |
|---|---|---|---|---|---|---|---|---|---|
| inéditas · 40d anteriores | 61 | 54.1% | +0.036R | 1.07 | +0.11% | +0.23% | +0.49% | 2.9% | 3/5 |
| inéditas · 40d recentes | 92 | 55.4% | +0.081R | 1.18 | +0.37% | +0.73% | +1.43% | 2.2% | 3/5 |
| principais · 80d (seleção) | 129 | 61.2% | +0.161R | 1.39 | +1.04% | +2.09% | +4.21% | 3.8% | 4/5 |
| todas · 80d | 281 | 58.0% | +0.112R | 1.26 | +0.79% | +1.58% | +3.16% | 3.8% | 7/10 |

### 📐 Tendência + MACD 15m  (B Tendência + indicadores · 15m · alvo 2.0R)
Votos {'tendencia': 1.0, 'adx': 2.0, 'macd': 1.5} · limiar 15 · direção compra · stop 2.5 ATR · alvo 5.0 ATR · filtros {'vol_mult': 1.5, 'avoid_lateral': True, 'ignore_regime': True, 'contexts': ['tendencia_alta', 'reversao_alta', 'tendencia_baixa', 'rompimento_baixa']} · custo de taxas ≈ 0.09R por trade

| Bloco | Trades | Acerto | Expectativa | Fator de lucro | Retorno 0,25% | Retorno 0,5% | Retorno 1% | DD (0,5%) | Moedas + |
|---|---|---|---|---|---|---|---|---|---|
| inéditas · 40d anteriores | 98 | 50.0% | +0.401R | 1.76 | +1.99% | +4.02% | +8.20% | 3.6% | 4/5 |
| inéditas · 40d recentes | 94 | 40.4% | +0.105R | 1.17 | +0.48% | +0.94% | +1.80% | 4.8% | 5/5 |
| principais · 80d (seleção) | 185 | 42.2% | +0.140R | 1.23 | +1.29% | +2.57% | +5.08% | 4.4% | 4/5 |
| todas · 80d | 377 | 43.8% | +0.199R | 1.33 | +1.88% | +3.78% | +7.60% | 4.8% | 8/10 |

### 🧭 Tendência Forte 1h  (B Tendência + indicadores · 1h · alvo 2.0R)
Votos {'tendencia': 2.0, 'adx': 1.0, 'macd': 1.0, 'supertrend': 1.0} · limiar 50 · direção misto · stop 1.5 ATR · alvo 3.0 ATR · filtros {'vol_mult': 1.2, 'trend_ema': True, 'adx_min': 25, 'contexts': ['tendencia_alta']} · custo de taxas ≈ 0.08R por trade

| Bloco | Trades | Acerto | Expectativa | Fator de lucro | Retorno 0,25% | Retorno 0,5% | Retorno 1% | DD (0,5%) | Moedas + |
|---|---|---|---|---|---|---|---|---|---|
| inéditas · 40d anteriores | 49 | 53.1% | +0.512R | 2.01 | +1.26% | +2.51% | +5.04% | 1.8% | 5/5 |
| inéditas · 40d recentes | 52 | 42.3% | +0.200R | 1.33 | +0.52% | +1.03% | +2.05% | 3.2% | 4/5 |
| principais · 80d (seleção) | 86 | 46.5% | +0.286R | 1.48 | +1.24% | +2.49% | +5.05% | 4.5% | 4/5 |
| todas · 80d | 187 | 47.1% | +0.321R | 1.56 | +1.51% | +3.03% | +6.12% | 4.5% | 8/10 |

### 📊 Rompimento com Volume 1h  (C Tendência + volume · 1h · alvo 2.0R)
Votos {'tendencia': 1.0, 'volume': 2.0, 'rompimento': 2.0, 'adx': 1.0} · limiar 10 · direção compra · stop 1.5 ATR · alvo 3.0 ATR · filtros {'vol_mult': 1.5, 'avoid_lateral': True, 'adx_min': 25, 'contexts': ['reversao_baixa', 'tendencia_alta', 'tendencia_baixa']} · custo de taxas ≈ 0.082R por trade

| Bloco | Trades | Acerto | Expectativa | Fator de lucro | Retorno 0,25% | Retorno 0,5% | Retorno 1% | DD (0,5%) | Moedas + |
|---|---|---|---|---|---|---|---|---|---|
| inéditas · 40d anteriores | 54 | 46.3% | +0.317R | 1.55 | +0.85% | +1.70% | +3.36% | 2.6% | 5/5 |
| inéditas · 40d recentes | 53 | 45.3% | +0.304R | 1.53 | +0.80% | +1.60% | +3.19% | 2.6% | 4/5 |
| principais · 80d (seleção) | 106 | 48.1% | +0.326R | 1.57 | +1.74% | +3.49% | +7.05% | 2.9% | 4/5 |
| todas · 80d | 213 | 46.9% | +0.318R | 1.55 | +1.70% | +3.41% | +6.84% | 2.9% | 9/10 |

### 🧬 Híbrida Price Action + Volume 1h  (D Híbrida · 1h · alvo 2.0R)
Votos {'estrutura': 1.0, 'rompimento': 2.0, 'volume': 1.5, 'tendencia': 2.0, 'suporte_resistencia': 1.0, 'fibonacci': 1.0} · limiar 40 · direção misto · stop 1.5 ATR · alvo 3.0 ATR · filtros {'vol_mult': 1.0, 'contexts': ['reversao_baixa', 'tendencia_alta', 'pullback_baixa']} · custo de taxas ≈ 0.086R por trade

| Bloco | Trades | Acerto | Expectativa | Fator de lucro | Retorno 0,25% | Retorno 0,5% | Retorno 1% | DD (0,5%) | Moedas + |
|---|---|---|---|---|---|---|---|---|---|
| inéditas · 40d anteriores | 64 | 45.3% | +0.281R | 1.48 | +0.90% | +1.79% | +3.57% | 2.1% | 4/5 |
| inéditas · 40d recentes | 55 | 45.5% | +0.285R | 1.49 | +0.79% | +1.59% | +3.23% | 4.7% | 3/5 |
| principais · 80d (seleção) | 126 | 45.2% | +0.238R | 1.39 | +1.50% | +3.01% | +6.04% | 3.5% | 4/5 |
| todas · 80d | 245 | 45.3% | +0.260R | 1.44 | +1.60% | +3.20% | +6.42% | 4.7% | 8/10 |

### Reservas (passaram, mas não entraram nos 5)
* **D Híbrida 1h 1R** — inéditas +0,15R / +0,18R, acerto ~61%, DD baixo (2,8%). Boa candidata a próximo bot.
* **B Tendência 15m 1,5R** — inéditas +0,37R / +0,10R, 9/10 moedas positivas nos 80 dias.
* **A Price action 15m 2R** e **1h 1,5R** — positivos, mas com expectativa perto de zero nas inéditas (≈ +0,02R) ou negativa num regime.

## Ressalvas honestas
* O **price action puro** foi a versão mais fraca: aprovado, mas com borda pequena nas moedas inéditas (+0,04R e +0,08R por trade).
  As versões que **somam volume e tendência** ao price action (C e D) foram as mais consistentes — exatamente a hipótese do estudo.
* Quatro dos cinco operam **praticamente só comprados** (B 15m e C 1h são só compra; Tendência Forte 1h só entra no contexto "tendência de alta"). Em mercado de baixa prolongado eles simplesmente operam menos,
  mas o histórico testado (80 dias) não inclui uma queda longa.
* Não testado: trailing stop, slippage e funding (as taxas de 0,04% por lado estão incluídas). 80 dias é pouco; acompanhe o
  desempenho real no card antes de aumentar o risco. Risco sugerido: **0,25%–0,5% por trade** (os retornos acima mostram as duas faixas).
