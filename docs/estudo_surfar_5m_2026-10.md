# Estudo: surfar a tendência e bot de 5m para banca de 50–100 USDT (out/2026)

Pergunta: um bot que opera só com stop (sem take profit), olha o 4h e o 15m e entra no 5m (às vezes no 15m), saindo quando a tendência/volume cansa, é uma boa estratégia?

## 1. A saída "surfar" (stop móvel) em entradas que já tinham vantagem (15m/1h)
Mesmas entradas dos 5 bots do estudo anterior, só trocando a saída (80 dias, 10 moedas, taxa 0,04%/lado):

| Bot | Alvo fixo | Sai com volume < 0,8× | Stop móvel 3 ATR |
|---|---|---|---|
| Tendência + MACD 15m | +0,19R | +0,16R | +0,26R |
| Rompimento com Volume 1h | +0,34R | +0,51R | +0,87R |
| Híbrida 1h | +0,29R | +0,26R | +0,59R |
| Tendência Forte 1h | +0,32R | +0,47R | +0,93R |
| Price Action Puro 1h | +0,12R | +0,09R | +0,25R |

O stop móvel ganhou nos 5. Os últimos 20 dias foram negativos nos bots de 1h (sem tendência, nada funciona).
Limitação: essas entradas já tinham sido escolhidas nos mesmos 80 dias.

## 2. Busca no 5m (futuros), 82 dias, 10 moedas
* Filtros novos: tendência do **4h** (`htf_trend`) e do **15m** (`mtf_trend`); saídas: alvo 1R/1,5R/2R ou surfar.
* Custo realista: **0,07% por lado** (taxa 0,05% + derrapagem 0,02%). No 5m o custo consome de 0,15R a 0,5R por operação.
* Seleção exigindo lucro em 3 blocos nas 5 moedas principais (40 dias anteriores, 27 de busca, 13 de validação);
  prova final nas 5 moedas inéditas, separando os dois regimes.
* Famílias: A price action, B tendência+indicadores, C tendência+volume, D híbrida, E reversão (Bollinger/estocástico), F tendência+VWAP.
* **Resultado: nenhuma configuração de A, B, C, F passou na seleção; D e E tiveram um candidato cada e só E ficou perto.**

### Especialistas de 5m que já existiam
Aprovados apenas nos 40 dias recentes, **perdem de −3% a −7% nos 40 dias anteriores** (1/10 moedas positivas).
Os cards agora mostram esse teste e 7 deles passaram de "aprovado" para "fraco". O Sniper Bollinger 5m fica em "ressalva" (+0,3%).

### Candidato: 🏄 Surfista de Reversão 5m (experimental)
Reversão (Bollinger 1,5 · reversão 2 · estocástico 1), limiar 45, 4h e 15m a favor, evita lateralidade,
stop inicial 2,5 ATR, stop móvel a 5 ATR, sem alvo.

| Bloco | Operações | Acerto | Expectativa | Fator de lucro | Retorno (1% risco) | Queda máx. | Moedas + |
|---|---|---|---|---|---|---|---|
| 80 dias | 397 | 35% | +0,157R | 1,26 | +6,9% (0,5% risco: +3,3%) | 15,3% | 7/10 |
| 40 dias anteriores | 193 | 34% | +0,061R | 1,10 | +1,0% | 9,0% | 5/10 |
| 40 dias recentes | 204 | 36% | +0,247R | 1,42 | +5,4% | 15,2% | 7/10 |
| Moedas inéditas, anteriores / recentes | — | — | +0,00R / +0,24R | — | — | — | 2/5 / 4/5 |

Não passou no critério (positivo nas inéditas nos dois regimes) → entra como **experimental, status "ressalva"**.

## Banca de 50–100 USDT
* Risco de 1–2% = 0,5 a 2 USDT por operação; a taxa de ida e volta de 0,14% pesa muito mais com stops curtos.
* Mínimo da Binance: 100 USDT de posição no BTC, 20 no ETH, 5 nas demais (o app avisa).
* Padrões novos: banca 100 USDT, risco 2% do saldo, meta +10 e limite −6 USDT/dia.
* Não testado: funding, trailing por volume ao vivo, mais de 82 dias.
