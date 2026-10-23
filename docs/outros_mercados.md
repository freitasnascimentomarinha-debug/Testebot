# Outros mercados: Forex, Commodities, Índices e Ações da B3 (out/2026)

Quatro páginas novas no menu **Outros mercados**, com o mesmo formato da cripto: gráfico ao vivo com indicadores, TradingView com ferramentas de desenho,
boleta e calculadora, bots, piloto automático, leitura do especialista e carteira simulada.

## Dados "ao vivo"
* Fonte: **Yahoo Finance** (API pública, sem chave). O gráfico e a cotação são atualizados sozinhos a cada consulta (15–30 s).
* Atraso: forex quase em tempo real; commodities (contratos futuros contínuos), índices e a B3 podem ter **atraso de até ~15 min**.
* **Mercado fechado** é detectado pelo horário do último negócio: a página mostra 🔴, o piloto automático fica em espera e ordens a mercado ficam bloqueadas.
* Limites do Yahoo (não é API oficial): pode oscilar ou limitar requisições, principalmente em servidores compartilhados; o app usa cache curto e dois hosts, mas sem
  fonte de reserva. Histórico: 5/15/30 min só ~60 dias; 1h e 4h ~2 anos; diário ~10 anos.
* Catálogo: **30 pares de forex**, **23 commodities**, **19 índices** do mundo e **60 ações da B3** (132 instrumentos).

## Como a simulação funciona
* A carteira é em dólar (USDT ≈ USD). Lucros e perdas em outras moedas (BRL, JPY, EUR…) são convertidos pela cotação do momento.
* Alavancagem simulada: forex até 30×, commodities e índices até 20×, **ações da B3 sem alavancagem e só compradas**. Liquidação por margem isolada ou cruzada
  (manutenção de 0,5%).
* Quantidade mínima: forex 100 unidades, commodities 0,01, índices 0,001, ações 1 (a calculadora avisa quando o risco escolhido não cabe).
* Custos por lado (spread/corretagem + derrapagem): forex 0,015%, commodities 0,04%, índices 0,03%, ações 0,08%.
* **Não simulado**: swap/juros overnight, dividendos, leilões, feriados específicos, lotes padrão da corretora e vendas a descoberto na B3.

## Pesquisa dos bots
Os bots da cripto não valem para estes mercados, então foi feita a mesma pesquisa: busca aleatória (5 famílias × 3 tipos de saída), seleção em instrumentos
"vistos" exigindo lucro nos **3 períodos** (40% / 40% / 20% do histórico) e prova em instrumentos **inéditos**, em **duas metades** do histórico. Só entram bots com
lucro nas duas metades; o selo **aprovado** exige ainda ≥ +0,05R por operação nas duas, ≥ 60% dos ativos positivos e lucro nas duas metades do período.
Sem prova num tempo gráfico, o bot fica bloqueado ali (ex.: forex em 5m/15m/30m/1h, ações em 5m).

| Mercado | Tempo | Bot | Selo | Período | Retorno (1% risco) | ≈ ao mês | Acerto | Pior queda | Ativos + | 1ª metade | 2ª metade |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Commodities | 1d | Híbrida Commodities 1d · surfa | aprovado | 9,0 anos | +14.2% | +0.12% | 24% | 10% | 10/10 | +8.8% | +4.9% |
| Commodities | 1d | Reversão Commodities 1d · surfa | aprovado | 9,0 anos | +9.1% | +0.08% | 45% | 5% | 10/10 | +4.5% | +4.3% |
| Commodities | 1d | Tendência + Volume Commodities 1d · 2:1 | aprovado | 9,0 anos | +17.1% | +0.14% | 42% | 12% | 10/10 | +11.8% | +5.2% |
| Commodities | 1h | Híbrida Commodities 1h · 1,5:1 | ressalva | 1,9 anos | +7.7% | +0.31% | 46% | 16% | 9/10 | +3.8% | +3.7% |
| Commodities | 1h | Tendência + MACD Commodities 1h · 2:1 | ressalva | 1,9 anos | +7.0% | +0.29% | 40% | 19% | 7/10 | +4.3% | +2.6% |
| Commodities | 4h | Híbrida Commodities 4h · surfa | aprovado | 1,8 anos | +8.3% | +0.37% | 34% | 8% | 8/10 | +3.2% | +5.4% |
| Commodities | 4h | Price Action Commodities 4h · surfa | aprovado | 1,8 anos | +6.5% | +0.29% | 31% | 9% | 8/10 | +3.3% | +4.1% |
| Commodities | 4h | Tendência + Volume Commodities 4h · surfa | aprovado | 1,8 anos | +7.0% | +0.31% | 39% | 6% | 7/10 | +2.1% | +5.0% |
| Forex | 1d | Reversão Forex 1d · 2:1 | aprovado | 9,0 anos | +6.9% | +0.06% | 43% | 13% | 6/10 | +2.7% | +3.8% |
| Forex | 1d | Reversão Forex 1d · surfa | aprovado | 9,0 anos | +6.4% | +0.06% | 31% | 15% | 7/10 | +2.3% | +3.7% |
| Forex | 4h | Reversão Forex 4h · 1,5:1 | aprovado | 1,8 anos | +8.3% | +0.36% | 53% | 8% | 8/10 | +6.0% | +1.8% |
| Forex | 4h | Reversão Forex 4h · 2:1 | ressalva | 1,8 anos | +6.4% | +0.28% | 46% | 7% | 7/10 | +5.4% | +0.7% |
| Índices | 1d | Reversão Índices 1d · 2:1 | aprovado | 8,9 anos | +14.1% | +0.12% | 50% | 12% | 9/10 | +4.9% | +8.3% |
| Índices | 1d | Reversão Índices 1d · surfa | aprovado | 8,9 anos | +21.9% | +0.18% | 35% | 14% | 9/10 | +6.0% | +14.9% |
| Índices | 1d | Tendência + MACD Índices 1d · surfa | aprovado | 8,9 anos | +17.4% | +0.15% | 35% | 24% | 8/10 | +5.8% | +10.5% |
| Índices | 1h | Reversão Índices 1h · 1,5:1 | ressalva | 1,8 anos | +2.4% | +0.11% | 50% | 9% | 7/10 | +1.2% | +1.3% |
| Índices | 1h | Reversão Índices 1h · 2:1 | aprovado | 1,8 anos | +12.3% | +0.52% | 44% | 13% | 9/10 | +4.9% | +7.1% |
| Índices | 1h | Reversão Índices 1h · surfa | aprovado | 1,8 anos | +14.7% | +0.61% | 42% | 6% | 10/10 | +8.7% | +5.5% |
| Índices | 4h | Tendência + MACD Índices 4h · 2:1 | aprovado | 529 dias | +5.6% | +0.31% | 44% | 10% | 8/10 | +4.5% | +1.1% |
| Ações B3 | 1d | Price Action Ações B3 1d · 2:1 | aprovado | 9,0 anos | +4.7% | +0.04% | 43% | 9% | 11/12 | +2.9% | +1.9% |
| Ações B3 | 1d | Tendência + Volume Ações B3 1d · 2:1 | aprovado | 9,0 anos | +5.3% | +0.05% | 43% | 8% | 9/12 | +3.1% | +2.0% |
| Ações B3 | 1d | Tendência + Volume Ações B3 1d · surfa | aprovado | 9,0 anos | +5.7% | +0.05% | 42% | 9% | 9/12 | +2.3% | +3.3% |
| Ações B3 | 1h | Híbrida Ações B3 1h · 1,5:1 | aprovado | 1,8 anos | +6.0% | +0.26% | 49% | 13% | 11/12 | +3.6% | +2.5% |
| Ações B3 | 1h | Reversão Ações B3 1h · surfa | aprovado | 1,8 anos | +13.9% | +0.58% | 29% | 23% | 11/12 | +7.4% | +7.1% |
| Ações B3 | 1h | Tendência + Volume Ações B3 1h · 2:1 | ressalva | 1,8 anos | +5.1% | +0.22% | 46% | 7% | 9/12 | +1.9% | +3.0% |

## Ressalvas honestas
* O histórico de 1h e 4h é de **~2 anos** (2024–2026): um único ciclo. Os bots diários cobrem ~10 anos. Pouco tempo para concluir muito.
* O forex foi o mais difícil: a vantagem é pequena e só apareceu em 4h e diário, com reversão à média. Em 5m a 1h nenhuma configuração passou na prova.
* Os retornos são em carteira composta com 1% de risco por operação e não incluem swap nem dividendos.
* Resultado passado não garante futuro; tudo aqui é simulado e educativo.
