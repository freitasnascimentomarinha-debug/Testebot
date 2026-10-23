# Pesquisa de estratégias — últimos 40 dias (13/09 a 23/10/2026)

## Objetivo

Encontrar personalidades (estratégias) para os bots que teriam dado resultado positivo nos últimos 40 dias,
**sem cair em sobreotimização** (ajustar parâmetros até o passado ficar bonito e o futuro dar errado).

## Contexto do mercado

| Moeda | Variação 40 d | Mínima → máxima | 1º trecho (busca) | 2º trecho (validação) |
|---|---|---|---|---|
| BTC | +5,6% | 74,9 mil → 87,4 mil | +6,9% | −1,3% |
| ETH | −4,7% | 2.315 → 2.807 | −1,4% | −3,5% |
| SOL | +2,6% | 95,7 → 125,0 | +7,3% | −4,5% |
| BNB | +1,3% | 703,8 → 810,2 | +2,1% | −0,8% |
| XRP | −3,3% | 1,25 → 1,66 | +2,2% | −5,5% |

Mercado lateral com oscilações largas; o trecho de busca foi de alta e o de validação, de queda.

## Método

1. **Dados reais**: candles de futuros perpétuos (OKX, espelho dos preços da Binance) e spot (Binance), 15m, 1h e 4h.
2. **Simulador**: o mesmo motor do app (14 habilidades, filtros, stop/alvo por ATR, ajuste do stop por
   suporte/resistência, entrada na abertura do candle seguinte, stop antes do alvo quando ambos cabem no mesmo
   candle, taxa de 0,05% por lado nos futuros e 0,10% no spot). Conferido: reproduz o backtest do app operação por
   operação.
3. **Busca**: ~12 mil combinações aleatórias de habilidades, pesos, limiar, direção, filtros e stop/alvo, avaliadas
   **apenas nos primeiros 27 dias** em BTC, ETH, SOL, BNB e XRP. Aprovadas: positivas em ≥ 4 das 5 moedas.
4. **Validações que a busca nunca viu**:
   - os **13 dias seguintes** (validação temporal);
   - os **40 dias anteriores** ao período (outro regime de mercado);
   - **5 moedas fora da busca** (DOGE, ADA, LINK, AVAX, LTC), nas duas janelas.
5. **Métrica**: R = resultado ÷ risco da operação (+1R = ganhou o que arriscou). O retorno em % considera **1% da
   banca arriscado por operação, com juros compostos** — banca final = banca × (1 + 0,01·R₁) × (1 + 0,01·R₂) × …

## O que a pesquisa mostrou

- 2.166 combinações passaram na busca, mas **as melhores da busca quase sempre fracassaram depois**: das 20 melhores
  em futuros 1h, só 1 seguiu positiva na validação; em spot só comprado, nenhuma. Isso é sobreotimização na prática.
- As estratégias **"só venda" de 15m** pareciam ótimas no período recente (que terminou em queda), mas foram
  negativas em 0 a 2 das 5 moedas nos 40 dias anteriores — **descartadas**: funcionavam só por causa do viés de queda.
- Spot só comprado não teve candidatas robustas: o trecho de validação foi de queda.
- O que sobreviveu tem um padrão claro: **futuros, 1h, comprado e vendido, operando só com força de tendência
  (ADX ≥ 25) a favor da EMA 200** — ou, no caso do rompimento, justamente antes da tendência (ADX ≤ 25).

## Estratégias aprovadas (futuros, 1h)

Retornos com 1% de risco por operação, média das 5 moedas (cada moeda como uma banca separada), já com taxas.

| Personalidade | Moedas da busca (40 d) | Moedas inéditas (40 d) | 40 dias anteriores | Pior queda | Acerto |
|---|---|---|---|---|---|
| 🌀 Pullback SuperTrend + Estocástico | **+8,0%** | **+5,8%** | +0,16R/op | 15,3% | ~29% |
| 🎯 Tendência Equilibrada | +4,2% | +5,0% (5/5 positivas) | +0,02R/op | 9,5% | ~50% |
| ☁️ Ichimoku com Força | +3,8% | +3,2% | **+0,23R/op** | 9,6% | ~26% |
| 📦 Rompimento de Consolidação | +2,4% | +3,4% (5/5 positivas) | −0,07R/op | **4,1%** | ~53% |
| ⚖️ Momentum Moderado | +3,4% | +3,6% | −0,01R/op | 6,4% | **~60%** |

As três primeiras foram positivas em **todos** os testes; as duas últimas, em quase todos (ficaram perto de zero nos
40 dias anteriores), com as menores quedas da banca.

### Detalhe por moeda (40 dias, 1% de risco por operação)

| Personalidade | BTC | ETH | SOL | BNB | XRP | DOGE | ADA | LINK | AVAX | LTC |
|---|---|---|---|---|---|---|---|---|---|---|
| Pullback SuperTrend | +3,9% | +16,7% | +7,1% | −4,6% | +17,1% | +8,2% | +9,3% | +7,7% | +12,8% | −9,1% |
| Tendência Equilibrada | +6,3% | +6,9% | −1,5% | −1,9% | +11,4% | +8,7% | +7,0% | +2,0% | +1,0% | +6,3% |
| Ichimoku com Força | +5,0% | +5,9% | −3,9% | −0,2% | +12,4% | −0,5% | +8,3% | −3,5% | +7,1% | +4,7% |
| Rompimento de Consolidação | +1,1% | +3,9% | −0,9% | +2,8% | +5,0% | +6,1% | +2,3% | +3,2% | +3,5% | +2,1% |
| Momentum Moderado | +6,7% | +4,0% | −2,1% | +1,9% | +6,3% | +13,0% | +6,6% | +1,3% | −1,6% | −1,3% |

## Como usar

1. Página **🏆 Personalidades → Biblioteca** → escolha a estratégia → **Usar neste bot** (Day Trade). O timeframe é
   ajustado para 1h automaticamente.
2. Acompanhe na carteira simulada antes de qualquer dinheiro real. O ranking passa a medir o desempenho real.
3. Prefira diversificar (2 ou 3 estratégias/moedas) e manter o risco por operação baixo (≤ 1%).

## Limitações

- 40 dias é pouco tempo; resultados passados não garantem resultados futuros.
- Testes sem a IA (só regras). Com o DeepSeek, as decisões podem mudar.
- Não inclui funding dos perpétuos nem slippage em momentos de alta volatilidade.
- Mesmo as aprovadas tiveram moedas negativas: nenhuma estratégia ganha sempre.
