"""Aprendendo: cinco vídeo-aulas narradas (voz Piper) sobre o sistema e a negociação com bots."""
import json
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets" / "aulas"

st.title("🎓 Aprendendo")
st.caption("Cinco vídeo-aulas curtas, com voz narrada, que explicam passo a passo cada parte do sistema e como negociar com os bots. "
           "Conteúdo educativo, com carteira simulada — não é recomendação de investimento.")

QUIZ = {
    "aula1": [
        ("Precisa de inteligência artificial para o bot abrir e fechar ordens?",
         ["Sim, sem a IA o bot não funciona", "Não: as regras decidem sozinhas e a IA é opcional", "Só no mercado à vista"], 1,
         "As regras do bot decidem sozinhas e sem custo. A IA explica o mercado e dá dicas; só interfere na ativação do bot se você permitir."),
        ("As ordens do sistema são executadas…",
         ["Na sua conta real da Binance", "Numa carteira simulada, com cotações reais", "Em dados inventados"], 1,
         "Cotações reais, ordens simuladas na conta demo da plataforma. As contas demo e real da Exchange ainda não recebem ordens nesta versão."),
        ("O que define o tamanho de cada ordem?",
         ["Uma meta de operações por dia", "A perda máxima por trade e a distância do stop", "A opinião da IA"], 1,
         "O tamanho sai da perda máxima por trade e do stop. Não há bloqueio por metas ou limites diários."),
    ],
    "aula2": [
        ("Quais indicadores vêm por padrão no gráfico?",
         ["Todos os 15", "Duas médias móveis e volume", "Só RSI"], 1, "O padrão é enxuto: duas médias móveis e volume. Os demais são opcionais."),
        ("O P&L aberto mostra…",
         ["O lucro ou prejuízo já realizado", "O lucro ou prejuízo das posições em andamento, com taxas", "A taxa de acerto"], 1,
         "É o resultado ainda em andamento, já descontadas as taxas."),
        ("Na carteira única…",
         ["Cada bot tem a sua banca", "Os três bots e as suas ordens manuais dividem a mesma banca", "Só o Day Trade opera"], 1,
         "Na separada, cada bot tem a sua subconta, boa para comparar um bot contra o outro."),
    ],
    "aula3": [
        ("Toda ordem no sistema precisa de…",
         ["Alvo (take profit)", "Stop loss", "Alavancagem de 10×"], 1, "O stop é obrigatório: ele define o risco e, a partir dele, o tamanho da posição."),
        ("Banca de 100 USDT, perda máxima de 2%, stop a 2% do preço. Quanto a posição pode perder se o stop for atingido?",
         ["Cerca de 2 USDT", "Cerca de 20 USDT", "100 USDT"], 0, "O tamanho da posição é calculado para que a perda no stop seja a perda máxima escolhida."),
        ("A alavancagem maior, no sistema…",
         ["Aumenta a perda por operação", "Reduz a margem usada e aproxima a liquidação", "Elimina as taxas"], 1,
         "A perda por trade é limitada pelo stop; a alavancagem muda a margem travada e a distância até a liquidação."),
    ],
    "aula4": [
        ("Por que testar em moedas inéditas e em dois períodos?",
         ["Para ter mais operações", "Para não se enganar com um bot ajustado a uma fase do mercado", "Porque a corretora exige"], 1,
         "Um bot pode brilhar numa fase e perder na outra. Os bots de reversão de 5m são o exemplo."),
        ("O selo \"Fraco\" num cartão significa…",
         ["Que o bot ainda não operou", "Que o resultado simulado foi ruim no teste", "Que o bot está desligado"], 1, "Foi negativo nos testes (por exemplo, nos 40 dias anteriores)."),
        ("O filtro de tendência do tempo maior…",
         ["Deixa o bot operar a favor do gráfico maior (ex.: 4h)", "Aumenta o alvo", "Desliga o stop"], 0, "No 15m exige o 4h a favor; no 5m exige o 4h e o 15m."),
    ],
    "aula5": [
        ("Quem fecha as posições quando o preço toca stop, alvo ou stop móvel?",
         ["A IA, se estiver ligada", "A carteira simulada, automaticamente", "Só você, manualmente"], 1,
         "Isso é automático e independe da IA. A IA só pode mandar fechar posições do próprio bot por mudança de cenário."),
        ("No modo \"surfar\"…",
         ["Há alvo fixo de 2R", "Não há alvo: o stop sobe junto com o preço", "O stop é removido"], 1, "Só existe o stop, que acompanha o preço a uma distância fixa."),
        ("Armar um plano condicional da leitura do especialista…",
         ["Abre a ordem imediatamente", "Só abre a ordem se o candle fechar confirmando o gatilho", "Dispensa o stop"], 1,
         "O gatilho é conferido pelo sistema a cada candle fechado; só então a ordem é montada."),
        ("Os números de desempenho das aulas medem…",
         ["As regras sozinhas (o efeito da IA não foi medido)", "A IA decidindo as entradas", "Operações reais na Binance"], 0,
         "Todos os testes são de regras, com candles reais e taxas."),
    ],
}


def fmt_t(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"


meta_file = ASSETS / "aulas.json"
if not meta_file.exists():
    st.warning("Os vídeos ainda não foram gerados. Rode `python tools/aulas/build.py`.")
    st.stop()
aulas = json.loads(meta_file.read_text(encoding="utf-8"))

done = st.session_state.setdefault("aulas_vistas", set())
st.progress(len(done) / len(aulas), text=f"{len(done)} de {len(aulas)} aulas concluídas nesta sessão")

labels = {a["id"]: f"{'✅ ' if a['id'] in done else ''}Aula {a['id'][-1]} · {a['titulo']} ({round(a['duracao_s'] / 60)} min)" for a in aulas}
tabs = st.tabs([labels[a["id"]] for a in aulas])
for tab, aula in zip(tabs, aulas):
    with tab:
        aid = aula["id"]
        st.subheader(f"Aula {aid[-1]} · {aula['titulo']}")
        st.write(aula["resumo"])
        caps = aula["capitulos"]
        start = st.selectbox("Ir para o capítulo", range(len(caps)), key=f"cap_{aid}",
                             format_func=lambda i, caps=caps: f"{fmt_t(caps[i]['t'])} · {caps[i]['titulo']}")
        video, vtt = ROOT / aula["video"], ROOT / aula["legenda"]
        if video.exists():
            st.video(str(video), start_time=int(caps[start]["t"]) if start else 0,
                     subtitles={"Português": str(vtt)} if vtt.exists() else None)
            st.caption("Dica: ative a legenda no botão CC do player. Voz sintética gerada com o Piper (pt_BR-faber-medium).")
        else:
            st.error("Vídeo não encontrado.")
        with st.expander("📜 Roteiro completo (texto da narração)"):
            for c in caps:
                st.markdown(f"**{fmt_t(c['t'])} · {c['titulo']}**")
                st.write(" ".join(c["fala"]))
        st.markdown("#### ✍️ Para fixar")
        right = 0
        answered = 0
        for qi, (q, opts, ok, why) in enumerate(QUIZ.get(aid, [])):
            ans = st.radio(f"{qi + 1}. {q}", opts, index=None, key=f"q_{aid}_{qi}")
            if ans is not None:
                answered += 1
                if opts.index(ans) == ok:
                    right += 1
                    st.success("Correto. " + why)
                else:
                    st.error("Quase. " + why)
        n_q = len(QUIZ.get(aid, []))
        if n_q and answered == n_q:
            st.info(f"Você acertou {right} de {n_q}.")
        if st.button("Marcar aula como concluída", key=f"done_{aid}", disabled=aid in done):
            done.add(aid)
            st.rerun()
