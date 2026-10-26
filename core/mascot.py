"""Mascote do Cripto Robô: um robozinho com uma moeda de bitcoin na antena, visor com olhos que piscam e um sorriso em forma de
gráfico subindo. SVG puro com animações em CSS (flutua, pisca, acena e a moeda brilha); usado na tela de login e no menu lateral."""
NAME = "Cripto Robô"
TAGLINE = "seu robô de trade de cripto"


def svg(size: int = 160, animated: bool = True, uid: str = "cr") -> str:
    a = animated
    style = f"""<style>
      .{uid}-float{{animation:{uid}-f 3.2s ease-in-out infinite}} @keyframes {uid}-f{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-6px)}}}}
      .{uid}-eye{{transform-box:fill-box;transform-origin:center;animation:{uid}-b 4.5s infinite}} @keyframes {uid}-b{{0%,92%,100%{{transform:scaleY(1)}}95%{{transform:scaleY(.1)}}}}
      .{uid}-arm{{transform-box:fill-box;transform-origin:10% 90%;animation:{uid}-w 2.4s ease-in-out infinite}} @keyframes {uid}-w{{0%,100%{{transform:rotate(0)}}50%{{transform:rotate(-22deg)}}}}
      .{uid}-coin{{animation:{uid}-g 2s ease-in-out infinite}} @keyframes {uid}-g{{0%,100%{{filter:drop-shadow(0 0 2px #f7931a)}}50%{{filter:drop-shadow(0 0 9px #ffb74d)}}}}
      .{uid}-chart{{stroke-dasharray:80;animation:{uid}-d 3s ease-in-out infinite}} @keyframes {uid}-d{{0%{{stroke-dashoffset:80}}45%,100%{{stroke-dashoffset:0}}}}
    </style>""" if a else ""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 230" width="{size}" height="{int(size * 1.15)}" role="img" aria-label="{NAME}">
  <title>{NAME}</title>{style}
  <defs>
    <linearGradient id="{uid}-h" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3ddbc6"/><stop offset="1" stop-color="#1a8f83"/></linearGradient>
    <linearGradient id="{uid}-b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a3350"/><stop offset="1" stop-color="#1a1f30"/></linearGradient>
    <radialGradient id="{uid}-c" cx=".35" cy=".35" r=".7"><stop offset="0" stop-color="#ffd27a"/><stop offset="1" stop-color="#f7931a"/></radialGradient>
  </defs>
  <ellipse cx="100" cy="220" rx="46" ry="6" fill="#000" opacity=".35"/>
  <g class="{uid}-float">
    <line x1="100" y1="44" x2="100" y2="24" stroke="#9aa6c4" stroke-width="4" stroke-linecap="round"/>
    <g class="{uid}-coin"><circle cx="100" cy="17" r="13" fill="url(#{uid}-c)" stroke="#c46f00" stroke-width="2"/>
      <text x="100" y="23" text-anchor="middle" font-family="Arial, sans-serif" font-weight="900" font-size="17" fill="#fff">₿</text></g>
    <rect x="27" y="74" width="16" height="34" rx="7" fill="#1a8f83" stroke="#0f5e56" stroke-width="2"/>
    <rect x="157" y="74" width="16" height="34" rx="7" fill="#1a8f83" stroke="#0f5e56" stroke-width="2"/>
    <circle cx="35" cy="91" r="4" fill="#d6fff8"/><circle cx="165" cy="91" r="4" fill="#d6fff8"/>
    <rect x="38" y="42" width="124" height="98" rx="30" fill="url(#{uid}-h)" stroke="#0f5e56" stroke-width="3"/>
    <rect x="52" y="58" width="96" height="62" rx="20" fill="#0b1220" stroke="#0f5e56" stroke-width="2"/>
    <ellipse class="{uid}-eye" cx="80" cy="80" rx="9" ry="11" fill="#7cf7e4"/><ellipse class="{uid}-eye" cx="120" cy="80" rx="9" ry="11" fill="#7cf7e4"/>
    <circle cx="83" cy="76" r="3" fill="#fff"/><circle cx="123" cy="76" r="3" fill="#fff"/>
    <polyline class="{uid}-chart" points="68,108 80,102 90,106 102,96 112,100 128,89" fill="none" stroke="#26e07f" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
    <polygon points="128,84 134,90 126,93" fill="#26e07f"/>
    <circle cx="62" cy="104" r="5" fill="#ff8fa3" opacity=".7"/><circle cx="138" cy="104" r="5" fill="#ff8fa3" opacity=".7"/>
    <rect x="88" y="138" width="24" height="8" rx="3" fill="#0f5e56"/>
    <rect x="58" y="144" width="84" height="58" rx="20" fill="url(#{uid}-b)" stroke="#3ddbc6" stroke-width="2.5"/>
    <rect x="76" y="156" width="48" height="30" rx="7" fill="#0b1220"/>
    <rect x="84" y="167" width="5" height="12" rx="1" fill="#26a69a"/><line x1="86.5" y1="162" x2="86.5" y2="183" stroke="#26a69a" stroke-width="1.5"/>
    <rect x="97" y="171" width="5" height="9" rx="1" fill="#ef5350"/><line x1="99.5" y1="166" x2="99.5" y2="184" stroke="#ef5350" stroke-width="1.5"/>
    <rect x="110" y="161" width="5" height="16" rx="1" fill="#26a69a"/><line x1="112.5" y1="158" x2="112.5" y2="181" stroke="#26a69a" stroke-width="1.5"/>
    <path d="M58 160 Q40 168 42 188" fill="none" stroke="#1a8f83" stroke-width="10" stroke-linecap="round"/>
    <circle cx="42" cy="190" r="8" fill="#3ddbc6" stroke="#0f5e56" stroke-width="2"/>
    <g class="{uid}-arm"><path d="M142 160 Q162 150 166 130" fill="none" stroke="#1a8f83" stroke-width="10" stroke-linecap="round"/>
      <circle cx="167" cy="126" r="8" fill="#3ddbc6" stroke="#0f5e56" stroke-width="2"/></g>
    <rect x="70" y="200" width="20" height="14" rx="6" fill="#1a8f83" stroke="#0f5e56" stroke-width="2"/>
    <rect x="110" y="200" width="20" height="14" rx="6" fill="#1a8f83" stroke="#0f5e56" stroke-width="2"/>
  </g>
</svg>"""
