import os
import re
import sqlite3
import ssl
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime
from difflib import SequenceMatcher

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="CYGLASER // Catálogo & Precios",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DB_PATH = "articulos.db"
FOTOS_DIR = "static_fotos"
os.makedirs(FOTOS_DIR, exist_ok=True)

# ----------------- ESTILOS FUTURISTAS SEGUROS (SOLO CSS) -----------------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800;900&family=Inter:wght@400;500;600;700&display=swap');
    
    .stApp {
        background: radial-gradient(circle at 15% 15%, #0f172a 0%, #020617 100%);
        font-family: 'Inter', sans-serif;
        color: #f1f5f9;
    }
    
    .laser-title {
        font-family: 'Orbitron', sans-serif;
        font-size: 1.85rem;
        font-weight: 900;
        letter-spacing: 2px;
        background: linear-gradient(90deg, #00f5d4 0%, #00bbf9 50%, #10b981 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 2px;
    }
    
    .laser-sub {
        font-size: 0.85rem;
        color: #94a3b8;
        letter-spacing: 1px;
        margin-bottom: 14px;
        text-transform: uppercase;
    }
    
    .precio-laser {
        font-family: 'Orbitron', sans-serif;
        font-size: 1.35rem;
        font-weight: 800;
        color: #10b981;
    }
    
    .total-laser {
        font-family: 'Orbitron', sans-serif;
        font-size: 1.55rem;
        font-weight: 900;
        color: #00f5d4;
        margin-top: 10px;
    }
    
    /* Pestañas */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: rgba(15, 23, 42, 0.7);
        border: 1px solid rgba(148, 163, 184, 0.2);
        border-radius: 8px;
        color: #94a3b8;
        padding: 8px 16px;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, rgba(0, 245, 212, 0.15), rgba(16, 185, 129, 0.15)) !important;
        border-color: #00f5d4 !important;
        color: #00f5d4 !important;
        font-weight: 700;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- BASE DE DATOS -----------------
def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(productos)")
        cols = [c['name'] for c in cur.fetchall()]
        if 'foto_url' not in cols:
            cur.execute("ALTER TABLE productos ADD COLUMN foto_url TEXT DEFAULT ''")
            conn.commit()

init_db()

@st.cache_data(ttl=300)
def cargar_catalogo():
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT codigo, nombre, precio, foto_url FROM productos WHERE habilitado = 'S' ORDER BY nombre ASC",
            conn
        )

# ----------------- SISTEMA DE IMÁGENES SEGURO Y COMPATIBLE -----------------
def extraer_url_directa(url):
    if not url:
        return ""
    url = str(url).strip()
    
    # Archivos locales subidos
    if url.startswith("local:"):
        nombre_arch = url.replace("local:", "").strip()
        ruta = os.path.join(FOTOS_DIR, nombre_arch)
        if os.path.exists(ruta):
            return ruta
        return ""
        
    # Google Drive (convierte links compartidos en endpoint de imagen directa)
    drive_match = re.search(r'drive\.google\.com/(?:file/d/|open\?id=|uc\?id=|thumbnail\?id=)([a-zA-Z0-9_-]+)', url)
    if drive_match:
        file_id = drive_match.group(1)
        return f"https://drive.google.com/thumbnail?id={file_id}&sz=w800"
        
    # Dropbox
    if "dropbox.com" in url:
        return url.replace("dl=0", "raw=1")
        
    return url

@st.cache_data(ttl=3600, show_spinner=False)
def descargar_bytes_imagen(url):
    """Descarga la imagen desde Python con bypass de SSL y User-Agent para evitar errores de React"""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            return resp.read()
    except Exception:
        return None

def mostrar_imagen(url_o_ruta, width=120):
    """Muestra la imagen usando componentes 100% nativos de Streamlit sin romper el DOM"""
    url_limpia = extraer_url_directa(url_o_ruta)
    
    if url_limpia:
        if os.path.exists(url_limpia):
            st.image(url_limpia, width=width)
            return
            
        # Si es URL web o Google Drive, descargar los bytes de forma segura
        if url_limpia.startswith("http"):
            datos_imagen = descargar_bytes_imagen(url_limpia)
            if datos_imagen:
                st.image(datos_imagen, width=width)
                return

    # Si no hay imagen o falló la descarga, renderizar un aviso nativo seguro
    st.info("📷 Sin foto")

# ----------------- MOTOR DE BÚSQUEDA PREDICTIVA -----------------
def normalizar(texto):
    if not texto:
        return ""
    t = unicodedata.normalize('NFKD', str(texto)).encode('ASCII', 'ignore').decode('utf-8').lower()
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    t = t.replace('z', 's').replace('c', 's')
    t = t.replace('v', 'b')
    t = t.replace('ll', 'y')
    t = t.replace('h', '')
    return ' '.join(t.split())

def obtener_sugerencias(query, max_resultados=50):
    df_items = cargar_catalogo()
    q_limpia = query.strip()
    
    if not q_limpia:
        return []
    
    if q_limpia.isdigit():
        df_cod = df_items[df_items['codigo'] == int(q_limpia)]
        if not df_cod.empty:
            it = df_cod.iloc[0]
            return [(it['codigo'], f"[{it['codigo']}] {it['nombre']} — ${it['precio']:,.2f}")]
            
    q_norm = normalizar(q_limpia)
    q_tokens = q_norm.split()
    if not q_tokens:
        return []
        
    primera_palabra = q_tokens[0]
    resto_palabras = q_tokens[1:]
    candidatos = []
    
    for _, row in df_items.iterrows():
        nom_orig = row['nombre']
        nom_norm = normalizar(nom_orig)
        nom_tokens = nom_norm.split()
        
        match_primera = 0.0
        pos_primera = -1
        
        for idx_w, w in enumerate(nom_tokens):
            if w == primera_palabra:
                score_w = 1.0
            elif w.startswith(primera_palabra) or primera_palabra.startswith(w):
                ratio_len = min(len(primera_palabra), len(w)) / max(len(primera_palabra), len(w))
                score_w = 0.88 + 0.12 * ratio_len
            elif primera_palabra in w or w in primera_palabra:
                score_w = 0.82
            else:
                score_w = SequenceMatcher(None, primera_palabra, w).ratio()
                
            if score_w > match_primera:
                match_primera = score_w
                pos_primera = idx_w
                
        # Filtro estricto: la primera palabra debe coincidir
        if match_primera < 0.74:
            continue
            
        scores_resto = []
        for rw in resto_palabras:
            max_rw = 0.0
            for w in nom_tokens:
                if w == rw:
                    max_rw = 1.0
                elif w.startswith(rw) or rw.startswith(w):
                    max_rw = max(max_rw, 0.95)
                elif rw in w or w in rw:
                    max_rw = max(max_rw, 0.85)
                else:
                    max_rw = max(max_rw, SequenceMatcher(None, rw, w).ratio())
            scores_resto.append(max_rw)
            
        bonus_pos = 0.35 if pos_primera == 0 else (0.15 if pos_primera == 1 else 0.0)
        
        if resto_palabras:
            promedio_resto = sum(scores_resto) / len(scores_resto)
            min_resto = min(scores_resto)
            if min_resto < 0.52:
                continue
            puntaje_total = (match_primera * 0.50) + (promedio_resto * 0.35) + bonus_pos
        else:
            puntaje_total = (match_primera * 0.70) + bonus_pos
            
        candidatos.append((puntaje_total, row))
        
    candidatos.sort(key=lambda x: x[0], reverse=True)
    return [(c[1]['codigo'], f"[{c[1]['codigo']}] {c[1]['nombre']} — ${c[1]['precio']:,.2f}") for c in candidatos[:max_resultados]]

def actualizar_producto(codigo, nuevo_precio, foto_url):
    hoy = datetime.now().strftime("%Y%m%d")
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT precio FROM productos WHERE codigo = ?", (codigo,))
        row = cur.fetchone()
        antiguo_precio = row['precio'] if row else 0.0
        
        cur.execute("""
            UPDATE productos 
            SET precio = ?, foto_url = ?, precio_anterior = ?, fecha_modificacion = ?
            WHERE codigo = ?
        """, (nuevo_precio, foto_url.strip(), antiguo_precio, hoy, codigo))
        conn.commit()
    cargar_catalogo.clear()
    descargar_bytes_imagen.clear()

# Inicializaciones de estado
if "lista_temporal" not in st.session_state:
    st.session_state.lista_temporal = []

if "cod_modificar_seleccionado" not in st.session_state:
    st.session_state.cod_modificar_seleccionado = None

# ----------------- ENCABEZADO Y TARJETAS -----------------
st.markdown('<div class="laser-title">CYGLASER // SISTEMA DE PRECIOS</div>', unsafe_allow_html=True)
st.markdown('<div class="laser-sub">Terminal de Cotización & Catálogo Digital</div>', unsafe_allow_html=True)

col_msg1, col_msg2 = st.columns(2)

txt_promo = "¡Somos fabricantes! Descuentos del 10% en compras mayores a $50.000 y del 15% en compras mayores a $100.000."
txt_local = "CyGlaser - Pte. Perón Oeste 363 (Horarios: 9:30 a 12:30 y 16:00 a 19:00 hs)."

with col_msg1:
    with st.container(border=True):
        st.markdown("**🏷️ PROMO FABRICANTE**")
        st.code(txt_promo, language=None)

with col_msg2:
    with st.container(border=True):
        st.markdown("**📍 LOCAL & HORARIOS**")
        st.code(txt_local, language=None)

st.markdown("<br>", unsafe_allow_html=True)

tabs = st.tabs(["⚡ Cotizador WhatsApp (1 a 3 productos)", "✏️ Modificar Producto (Nombre o Cód.)", "➕ Nuevo Producto"])

# 1. PESTAÑA PRINCIPAL: COTIZADOR
with tabs[0]:
    col_busq, col_cant = st.columns([3, 1])
    with col_busq:
        busqueda_txt = st.text_input(
            "🔎 Buscar artículo (precedencia a la 1ª palabra):",
            placeholder="Ej: casita, alajero, pino pas, mate imprial, 2200...",
            key="input_busq"
        )
    with col_cant:
        cant_input = st.number_input("Cantidad:", min_value=1, value=1, step=1)

    sugerencias = obtener_sugerencias(busqueda_txt, max_resultados=50) if busqueda_txt else []

    if sugerencias:
        dict_opciones = {etiqueta: cod for cod, etiqueta in sugerencias}
        seleccion_etiqueta = st.selectbox(
            f"Seleccioná de la lista ({len(sugerencias)} resultados):",
            options=list(dict_opciones.keys()),
            key="combo_sugerencias"
        )
        
        cod_seleccionado = dict_opciones[seleccion_etiqueta]
        df_cat = cargar_catalogo()
        prod_data = df_cat[df_cat['codigo'] == cod_seleccionado].iloc[0]
        
        with st.container(border=True):
            c_preview_foto, c_preview_datos, c_preview_btn = st.columns([1.2, 3.8, 2])
            
            with c_preview_foto:
                url_foto = str(prod_data['foto_url'] or "").strip()
                mostrar_imagen(url_foto, width=120)
                    
            with c_preview_datos:
                st.markdown(f"**[{prod_data['codigo']}] {prod_data['nombre']}**")
                precio_u = float(prod_data['precio'] or 0.0)
                subtotal_u = precio_u * cant_input
                if cant_input > 1:
                    st.markdown(f"<span class='precio-laser'>${subtotal_u:,.2f}</span> <small style='color:#94a3b8;'>(x{cant_input} u.)</small>", unsafe_allow_html=True)
                    st.caption(f"Unitario: ${precio_u:,.2f}")
                else:
                    st.markdown(f"<span class='precio-laser'>${precio_u:,.2f}</span>", unsafe_allow_html=True)
                    
            with c_preview_btn:
                bloqueado = len(st.session_state.lista_temporal) >= 3
                if st.button("➕ Agregar al presupuesto", type="primary", use_container_width=True, disabled=bloqueado):
                    st.session_state.lista_temporal.append({
                        "codigo": int(prod_data['codigo']),
                        "nombre": str(prod_data['nombre']),
                        "precio": float(prod_data['precio'] or 0.0),
                        "cantidad": int(cant_input),
                        "foto_url": url_foto
                    })
                    st.rerun()
                if bloqueado:
                    st.caption("⚠️ Máximo de 3 productos alcanzado.")
            
    elif busqueda_txt:
        st.warning("No se encontraron productos que coincidan con la primera palabra buscada.")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # LISTA TEMPORAL
    st.markdown(f"#### 📋 Lista acumulada para el cliente ({len(st.session_state.lista_temporal)} / 3)")
    
    if st.session_state.lista_temporal:
        total_acumulado = 0.0
        lineas_mensaje = []
        
        for idx, item in enumerate(st.session_state.lista_temporal):
            subtotal = item['precio'] * item['cantidad']
            total_acumulado += subtotal
            
            if item['cantidad'] > 1:
                linea = f"• {item['nombre']} (x{item['cantidad']} u.): ${subtotal:,.2f} (${item['precio']:,.2f} c/u)"
            else:
                linea = f"• {item['nombre']}: ${item['precio']:,.2f}"
                
            if item['foto_url'] and str(item['foto_url']).strip().startswith("http"):
                linea += f"\n  Foto: {item['foto_url'].strip()}"
                    
            lineas_mensaje.append(linea)
            
            with st.container(border=True):
                c_img, c_desc, c_subt, c_del = st.columns([1, 4.5, 2, 1])
                
                with c_img:
                    mostrar_imagen(item['foto_url'], width=80)
                        
                with c_desc:
                    st.markdown(f"**[{item['codigo']}] {item['nombre']}**")
                    if item['cantidad'] > 1:
                        st.caption(f"Cantidad: {item['cantidad']} u. | Unitario: ${item['precio']:,.2f}")
                with c_subt:
                    st.markdown(f"<span class='precio-laser'>${subtotal:,.2f}</span>", unsafe_allow_html=True)
                with c_del:
                    if st.button("❌", key=f"del_{idx}", help="Quitar de la lista"):
                        st.session_state.lista_temporal.pop(idx)
                        st.rerun()

        st.markdown(f"<div class='total-laser'>TOTAL: ${total_acumulado:,.2f}</div>", unsafe_allow_html=True)
        st.write("")

        if len(st.session_state.lista_temporal) > 1:
            texto_final = "\n".join(lineas_mensaje) + f"\n\nTotal: ${total_acumulado:,.2f}"
        else:
            it = st.session_state.lista_temporal[0]
            if it['cantidad'] > 1:
                texto_final = f"{it['nombre']} (x{it['cantidad']} u.): ${total_acumulado:,.2f} (${it['precio']:,.2f} c/u)"
            else:
                texto_final = f"{it['nombre']}: ${it['precio']:,.2f}"
            if it['foto_url'] and str(it['foto_url']).strip().startswith("http"):
                texto_final += f"\nFoto: {it['foto_url'].strip()}"

        url_wsp = f"https://api.whatsapp.com/send?text={urllib.parse.quote(texto_final)}"

        c_act1, c_act2, c_act3 = st.columns([3, 1, 1])
        with c_act1:
            st.code(texto_final, language=None)
        with c_act2:
            st.link_button("📲 Enviar a WhatsApp", url_wsp, use_container_width=True)
        with c_act3:
            if st.button("🗑️ Limpiar lista", type="secondary", use_container_width=True):
                st.session_state.lista_temporal = []
                st.rerun()
    else:
        st.info("La lista está vacía. Buscá un producto arriba y tocalo para agregarlo.")

# 2. PESTAÑA: MODIFICACIÓN TOTALMENTE RESISTENTE
with tabs[1]:
    st.subheader("Modificar Precio y Foto de un Producto")
    
    txt_mod = st.text_input(
        "1️⃣ Buscá el artículo a modificar (por nombre o código):",
        placeholder="Ej: casita, alajero 14, 2200...",
        key="search_mod_input"
    )
    
    sug_mod = obtener_sugerencias(txt_mod, max_resultados=40) if txt_mod else []
    
    if sug_mod:
        dict_mod = {etiq: cod for cod, etiq in sug_mod}
        sel_mod = st.selectbox(
            "Seleccioná el producto exacto:",
            options=list(dict_mod.keys()),
            key="combo_mod_seleccion"
        )
        st.session_state.cod_modificar_seleccionado = dict_mod[sel_mod]
    elif txt_mod.strip().isdigit():
        st.session_state.cod_modificar_seleccionado = int(txt_mod.strip())
        
    cod_target = st.session_state.cod_modificar_seleccionado
    
    if cod_target:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT codigo, nombre, precio, foto_url FROM productos WHERE codigo = ?", (cod_target,))
            item = cur.fetchone()
            
        if item:
            with st.container(border=True):
                st.markdown(f"### 📦 [{item['codigo']}] {item['nombre']}")
                
                # Vista previa actual usando st.image seguro
                c_prev_actual_img, c_prev_actual_info = st.columns([1.5, 3])
                with c_prev_actual_img:
                    st.caption("Foto actual:")
                    mostrar_imagen(item['foto_url'], width=140)
                with c_prev_actual_info:
                    st.caption("Precio actual en base:")
                    st.markdown(f"<span class='precio-laser'>${float(item['precio'] or 0.0):,.2f}</span>", unsafe_allow_html=True)
                
                st.markdown("---")
                
                # Formulario atómico (resistente a pérdida de estado y a incógnito)
                with st.form(key=f"form_guardar_mod_{item['codigo']}"):
                    col_f1, col_f2 = st.columns(2)
                    
                    with col_f1:
                        nuevo_precio_val = st.number_input(
                            "Nuevo Precio de Venta ($):",
                            min_value=0.0,
                            value=float(item['precio'] or 0.0),
                            step=50.0
                        )
                        nuevo_link_val = st.text_input(
                            "Link a la foto (Google Drive, Web directa, etc.):",
                            value=str(item['foto_url'] or "").strip(),
                            help="Pegá el link compartido de Drive o la URL de la imagen."
                        )
                    
                    with col_f2:
                        st.caption("Subir foto desde este dispositivo (opcional):")
                        archivo_subido = st.file_uploader("Elegir imagen local", type=["jpg", "jpeg", "png"])
                        
                    btn_guardar = st.form_submit_button("💾 Guardar Cambios", type="primary", use_container_width=True)
                    
                    if btn_guardar:
                        link_final = nuevo_link_val.strip()
                        if archivo_subido is not None:
                            nom_guardado = f"art_{item['codigo']}_{archivo_subido.name}"
                            ruta_local = os.path.join(FOTOS_DIR, nom_guardado)
                            with open(ruta_local, "wb") as f_out:
                                f_out.write(archivo_subido.getbuffer())
                            link_final = f"local:{nom_guardado}"
                            
                        actualizar_producto(item['codigo'], nuevo_precio_val, link_final)
                        st.success(f"¡Producto [{item['codigo']}] actualizado correctamente!")
                        st.rerun()
        else:
            st.warning("No se encontró ningún artículo con ese código.")
    else:
        st.info("Escribí el nombre o código arriba para cargar el producto.")

# 3. PESTAÑA: ALTA RÁPIDA
with tabs[2]:
    st.subheader("Registrar Artículo Nuevo")
    with st.form("form_alta"):
        col1, col2 = st.columns(2)
        with col1:
            nuevo_cod = st.number_input("Código único:", min_value=1, step=1, value=5000)
            nuevo_nom = st.text_input("Descripción / Nombre:")
        with col2:
            nuevo_precio = st.number_input("Precio de venta ($):", min_value=0.0, step=100.0, value=1500.0)
            nuevo_link = st.text_input("Link de la foto (Drive o web):", placeholder="https://...")
            
        btn_crear = st.form_submit_button("Crear Artículo", use_container_width=True)
        if btn_crear:
            if not nuevo_nom.strip():
                st.error("Debes ingresar una descripción.")
            else:
                hoy = datetime.now().strftime("%Y%m%d")
                with get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO productos (codigo, nombre, precio, foto_url, habilitado, fecha_alta, fecha_modificacion)
                        VALUES (?, ?, ?, ?, 'S', ?, ?)
                    """, (nuevo_cod, nuevo_nom.strip().upper(), nuevo_precio, nuevo_link.strip(), hoy, hoy))
                    conn.commit()
                cargar_catalogo.clear()
                st.success(f"Artículo {nuevo_cod} creado con éxito.")