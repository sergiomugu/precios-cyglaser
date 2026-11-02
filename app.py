import re
import sqlite3
import unicodedata
import urllib.parse
from datetime import datetime
from difflib import SequenceMatcher

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Precios & Presupuesto WhatsApp",
    page_icon="🏷️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DB_PATH = "articulos.db"

# Estilos CSS
st.markdown("""
<style>
    .precio-destacado {
        font-size: 1.3rem;
        font-weight: 700;
        color: #15803d;
    }
    .total-general {
        font-size: 1.45rem;
        font-weight: 800;
        color: #0f172a;
        margin-top: 10px;
    }
    .sin-foto-box {
        display: flex;
        align-items: center;
        justify-content: center;
        background-color: #f1f5f9;
        border: 1px dashed #cbd5e1;
        border-radius: 8px;
        height: 100px;
        width: 100px;
        color: #94a3b8;
        font-size: 0.8rem;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

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
            "SELECT codigo, nombre, precio, foto_url FROM productos WHERE habilitado = 'S'",
            conn
        )

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
                
        if match_primera < 0.75:
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
            if min_resto < 0.55:
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

if "lista_temporal" not in st.session_state:
    st.session_state.lista_temporal = []

st.title("CYGLASER -- LISTA DE PRECIOS ONLINE")
# --- TARJETAS FIJAS DE MENSAJES RÁPIDOS ---
st.caption("📌 Mensajes Rápidos para Clientes (Tocar para copiar):")
col_msg1, col_msg2 = st.columns(2)

txt_promo = "¡Somos fabricantes! Descuentos del 10% en compras mayores a $50.000 y del 15% en compras mayores a $100.000."
txt_local = "CyGlaser - Pte. Perón Oeste 363 (Horarios: 9:30 a 12:30 y 16:00 a 19:00 hs)."

with col_msg1:
    st.markdown("**🏷️ Descuentos & Fabricación**")
    st.code(txt_promo, language=None)

with col_msg2:
    st.markdown("**📍 Dirección y Horarios**")
    st.code(txt_local, language=None)

st.divider()

tabs = st.tabs(["🛒 Buscador & Lista WhatsApp (1 a 3 productos)", "✏️ Modificar Precio / Foto", "➕ Nuevo Producto"])

# 1. PESTAÑA PRINCIPAL
with tabs[0]:
    st.subheader("Buscador Predictivo")
    
    col_busq, col_cant = st.columns([3, 1])
    with col_busq:
        busqueda_txt = st.text_input(
            "Buscar por palabra clave o código:",
            placeholder="Ej: casita, alajero, caja te 4, pino pas, mate imprial...",
            key="input_busq"
        )
    with col_cant:
        cant_input = st.number_input("Cantidad:", min_value=1, value=1, step=1)

    sugerencias = obtener_sugerencias(busqueda_txt, max_resultados=50) if busqueda_txt else []

    if sugerencias:
        dict_opciones = {etiqueta: cod for cod, etiqueta in sugerencias}
        seleccion_etiqueta = st.selectbox(
            f"Seleccioná el producto ({len(sugerencias)} encontrados):",
            options=list(dict_opciones.keys()),
            key="combo_sugerencias"
        )
        
        cod_seleccionado = dict_opciones[seleccion_etiqueta]
        df_cat = cargar_catalogo()
        prod_data = df_cat[df_cat['codigo'] == cod_seleccionado].iloc[0]
        
        # --- VISTA PREVIA DEL PRODUCTO SELECCIONADO (CON FOTO VISIBLE) ---
        with st.container():
            c_preview_foto, c_preview_datos, c_preview_btn = st.columns([1, 3, 2])
            
            with c_preview_foto:
                url_foto = str(prod_data['foto_url'] or "").strip()
                if url_foto.startswith("http"):
                    st.image(url_foto, width=130, caption="Foto del producto")
                else:
                    st.markdown("<div class='sin-foto-box'>📷<br>Sin foto</div>", unsafe_allow_html=True)
                    
            with c_preview_datos:
                st.markdown(f"**[{prod_data['codigo']}] {prod_data['nombre']}**")
                precio_u = float(prod_data['precio'] or 0.0)
                subtotal_u = precio_u * cant_input
                if cant_input > 1:
                    st.markdown(f"<span class='precio-destacado'>${subtotal_u:,.2f}</span> <small>(x{cant_input} u.)</small>", unsafe_allow_html=True)
                    st.caption(f"Precio unitario: ${precio_u:,.2f}")
                else:
                    st.markdown(f"<span class='precio-destacado'>${precio_u:,.2f}</span>", unsafe_allow_html=True)
                    
            with c_preview_btn:
                bloqueado = len(st.session_state.lista_temporal) >= 3
                if st.button("➕ Agregar a la lista", type="primary", use_container_width=True, disabled=bloqueado):
                    st.session_state.lista_temporal.append({
                        "codigo": int(prod_data['codigo']),
                        "nombre": str(prod_data['nombre']),
                        "precio": float(prod_data['precio'] or 0.0),
                        "cantidad": int(cant_input),
                        "foto_url": url_foto
                    })
                    st.rerun()
                if bloqueado:
                    st.caption("⚠️ Límite de 3 productos alcanzado.")
    elif busqueda_txt:
        st.warning("No se encontraron productos que coincidan con la primera palabra buscada.")

    st.markdown("---")
    
    # LISTA TEMPORAL (CON FOTOS INCLUIDAS)
    st.subheader(f"📋 Productos en lista para cotizar ({len(st.session_state.lista_temporal)} / 3)")
    
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
                
            if item['foto_url'] and item['foto_url'].startswith("http"):
                linea += f"\n  Foto: {item['foto_url']}"
                
            lineas_mensaje.append(linea)
            
            # Tarjeta de producto en lista con su imagen
            with st.container():
                c_img, c_desc, c_subt, c_del = st.columns([1, 4, 2, 1])
                
                with c_img:
                    if item['foto_url'] and item['foto_url'].startswith("http"):
                        st.image(item['foto_url'], width=85)
                    else:
                        st.markdown("<div class='sin-foto-box' style='height:75px;width:75px;'>📷</div>", unsafe_allow_html=True)
                        
                with c_desc:
                    st.markdown(f"**[{item['codigo']}] {item['nombre']}**")
                    if item['cantidad'] > 1:
                        st.caption(f"Cantidad: {item['cantidad']} u. | Unitario: ${item['precio']:,.2f}")
                with c_subt:
                    st.markdown(f"<span class='precio-destacado'>${subtotal:,.2f}</span>", unsafe_allow_html=True)
                with c_del:
                    if st.button("❌", key=f"del_{idx}", help="Quitar de la lista"):
                        st.session_state.lista_temporal.pop(idx)
                        st.rerun()

        st.markdown(f"<div class='total-general'>TOTAL: ${total_acumulado:,.2f}</div>", unsafe_allow_html=True)
        st.write("")

        if len(st.session_state.lista_temporal) > 1:
            texto_final = "\n".join(lineas_mensaje) + f"\n\nTotal: ${total_acumulado:,.2f}"
        else:
            it = st.session_state.lista_temporal[0]
            if it['cantidad'] > 1:
                texto_final = f"{it['nombre']} (x{it['cantidad']} u.): ${total_acumulado:,.2f} (${it['precio']:,.2f} c/u)"
            else:
                texto_final = f"{it['nombre']}: ${it['precio']:,.2f}"
            if it['foto_url'] and it['foto_url'].startswith("http"):
                texto_final += f"\nFoto: {it['foto_url']}"

        url_wsp = f"https://api.whatsapp.com/send?text={urllib.parse.quote(texto_final)}"

        c_act1, c_act2, c_act3 = st.columns([3, 1, 1])
        with c_act1:
            st.code(texto_final, language=None)
        with c_act2:
            st.link_button("📲 Enviar WhatsApp", url_wsp, use_container_width=True)
        with c_act3:
            if st.button("🗑️ Limpiar lista", type="secondary", use_container_width=True):
                st.session_state.lista_temporal = []
                st.rerun()
    else:
        st.info("La lista está vacía. Seleccioná un producto arriba y tocá '➕ Agregar a la lista'.")

# 2. PESTAÑA MODIFICAR PRECIO / FOTO
with tabs[1]:
    st.subheader("Actualizar Precio o Foto de un Producto")
    cod_edit = st.number_input("Ingresá el Código del artículo:", min_value=1, step=1, value=1)
    
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT codigo, nombre, precio, foto_url FROM productos WHERE codigo = ?", (cod_edit,))
        item = cur.fetchone()
        
    if item:
        st.info(f"**Artículo:** {item['nombre']}")
        p_actual = float(item['precio'] or 0.0)
        nuevo_p = st.number_input("Precio de Venta ($):", min_value=0.0, value=p_actual, step=50.0)
        
        foto_actual = item['foto_url'] or ""
        nueva_foto = st.text_input("Link de la foto (URL directa):", value=foto_actual, placeholder="https://i.imgur.com/foto.jpg")
        
        if nueva_foto.strip().startswith("http"):
            st.image(nueva_foto.strip(), width=160, caption="Vista previa")
            
        if st.button("💾 Guardar Cambios", type="primary", use_container_width=True):
            actualizar_producto(cod_edit, nuevo_p, nueva_foto)
            st.success("¡Datos guardados con éxito!")
            st.rerun()
    else:
        st.warning(f"No existe el artículo con código {cod_edit}.")

# 3. PESTAÑA ALTA RÁPIDA
with tabs[2]:
    st.subheader("Registrar Artículo Nuevo")
    with st.form("form_alta"):
        col1, col2 = st.columns(2)
        with col1:
            nuevo_cod = st.number_input("Código único:", min_value=1, step=1, value=5000)
            nuevo_nom = st.text_input("Descripción / Nombre:")
        with col2:
            nuevo_precio = st.number_input("Precio de venta ($):", min_value=0.0, step=100.0, value=1500.0)
            nuevo_link = st.text_input("Link de la foto (opcional):", placeholder="https://...")
            
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