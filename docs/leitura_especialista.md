# Leitura do especialista (IA + consultor técnico)

Ao clicar em **Analisar agora** (ou a cada candle com o piloto ligado) o bot produz, além da decisão imediata, uma leitura didática:

* **Cenário**: contexto do gráfico, força da tendência (ADX, médias), volume relativo, tendência do tempo maior, suportes e resistências, sempre com números.
* **Melhor oportunidade no tempo gráfico atual** e uma **dica**.
* **Melhor bot para o momento**: ranking dos bots prontos pelo desempenho simulado *no contexto atual* (R por operação, selo, teste dos 40 dias anteriores,
  mesmo tempo gráfico, direção compatível com o viés). Amostras pequenas pesam menos. Só é recomendado um bot com vantagem comprovada no contexto; se nenhum tiver,
  a recomendação é aguardar. A IA só pode escolher entre os candidatos (id validado pelo código).
* **Plano condicional**: "comprar/vender se um candle de X fechar acima/abaixo de N, com volume ≥ Y× a média, usando a personalidade Z; vale por K candles; cai se o preço chegar a W".

## Quem faz o quê
| Parte | Quem |
|---|---|
| Medir o cenário, ranquear bots, plano padrão | Código (`core/advisor.py`), funciona sem IA |
| Escrever a análise, escolher entre os candidatos, propor o gatilho | IA (DeepSeek via OpenRouter) |
| Validar bot e gatilho (lado do preço, distância, validade) | Código (`ai.build_advice`, `advisor.make_plan`) |
| Conferir o gatilho a cada candle fechado | Código (`engine.check_armed_plan`) — nunca a IA |
| Aprovar e abrir a ordem | Gestor de risco + carteira simulada |

## Armar o plano
* Manual: botão **Armar este plano** (vale para planos de regras ou da IA).
* Automático: piloto ligado + opção "armar sozinho os planos da IA" (aba IA). Planos gerados só por regras nunca são armados sozinhos.
* O gatilho só considera candles que fecham **depois** do armamento; se disparou num candle antigo, o plano é descartado ("perdido").
* Estados: pendente, disparou, invalidado, expirado, perdido. O plano é desarmado ao disparar, cair ou expirar.
* A ordem usa stop/alvo (ou stop móvel) da personalidade do plano e passa pelo gestor de risco.

## Limitações
* Entradas condicionais deste tipo **não têm backtest**.
* A qualidade da análise da IA depende do modelo; o código valida estrutura e coerência numérica, não a opinião técnica.
