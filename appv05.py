import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from supabase import create_client
from datetime import date
import numpy as np
import calendar
import json
import time
import re

# --- BIBLIOTECAS DE IA ---
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

# --- 1. CONFIGURAÇÃO GERAL ---
st.set_page_config(page_title="Gestão de Metas", layout="wide", page_icon="🚀")

st.markdown("""
<style>
    .metric-card { background-color: #f0f2f6; border-radius: 10px; padding: 20px; text-align: center; box-shadow: 2px 2px 5px rgba(0,0,0,0.1); }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    /* Estilo para avisos dentro de modais */
    .warning-box { background-color: #fff3cd; color: #856404; padding: 15px; border-radius: 5px; border: 1px solid #ffeeba; margin-bottom: 15px; text-align: center; }
</style>
""", unsafe_allow_html=True)

MESES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto", 
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
}

# --- 2. CONEXÃO SUPABASE ---
@st.cache_resource
def init_connection():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = init_connection()

# --- CLASSE ANALISTA VIRTUAL ---
class GeminiAnalista:
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model_name = self._obter_modelo_disponivel()
        self.model = genai.GenerativeModel(self.model_name)

    def _obter_modelo_disponivel(self):
        try:
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    if 'gemini' in m.name: return m.name
            return 'gemini-pro'
        except: return 'gemini-pro'

    def analisar(self, df, pergunta, nome_empresa, historico_chat=None):
        df_view = df.copy()
        for col in df_view.columns:
            if pd.api.types.is_datetime64_any_dtype(df_view[col]):
                df_view[col] = df_view[col].dt.strftime('%Y-%m-%d')
        
        info = df_view.dtypes.to_string()
        head = df_view.head(3).to_string()

        contexto_str = ""
        if historico_chat:
            ultimas = historico_chat[-4:]
            for msg in ultimas:
                role = "Usuário" if msg["role"] == "user" else "IA"
                contexto_str += f"{role}: {msg['content']}\n"

        prompt = f"""
        Você é um Analista de Dados Python Sênior.
        
        DADOS DISPONÍVEIS (Apenas desta empresa):
        Colunas: {info}
        Amostra: {head}
        
        HISTÓRICO DA CONVERSA:
        {contexto_str}
        
        PERGUNTA ATUAL: "{pergunta}"
        
        REGRAS DE OURO:
        1. Para perguntas sobre tempo (Dia, Mês, Ano, Dia da Semana), AGRUPE e SOME os valores.
           Ex: df.groupby('data_venda')['valor_venda'].sum()
        
        2. IMPORTANTE: O Pandas retorna dias em Inglês. Se a resposta tiver dias da semana, TRADUZA PARA PORTUGUÊS (ex: Monday->Segunda).
        
        3. Salve a resposta final (texto formatado) na variável 'resultado'.
        4. Formate dinheiro como "R$ X.XXX,XX".
        5. Retorne APENAS o código Python. Sem markdown.
        """

        max_tentativas = 3
        for tentativa in range(max_tentativas):
            try:
                response = self.model.generate_content(prompt)
                codigo = re.sub(r"```python|```", "", response.text).strip()
                
                local_vars = {"df": df, "pd": pd, "np": np}
                exec(codigo, {}, local_vars)
                
                if "resultado" in local_vars:
                    resposta_final = local_vars["resultado"]
                    return f"{resposta_final}\n\n*Você está consultando dados da empresa: {nome_empresa}*"
                else:
                    return "O código rodou mas não gerou a resposta."

            except google_exceptions.ResourceExhausted:
                wait_time = (tentativa + 1) * 8
                with st.spinner(f"Alta demanda na IA... Aguardando {wait_time}s..."):
                    time.sleep(wait_time)
                if tentativa == 1: self.model = genai.GenerativeModel('gemini-pro')
                continue
                
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    time.sleep(5)
                    continue
                return f"Erro técnico: {str(e)}"
        
        return "⚠️ O sistema de IA está sobrecarregado no momento. Tente novamente em 1 minuto."

# --- 3. SISTEMA DE DIÁLOGOS (POPUPS) ---

@st.dialog("🚫 Data Inválida")
def alerta_data_futura():
    st.error("Não é permitido registrar vendas com data futura!")
    st.write("Por favor, verifique a data selecionada e tente novamente.")
    if st.button("OK, Entendi", use_container_width=True):
        st.rerun()

@st.dialog("⚠️ Gerenciar Lançamento")
def gerenciar_venda_dialog(id_venda, data_venda, valor_atual, cid):
    st.markdown("""
        <div class="warning-box">
            <b>ATENÇÃO:</b> Você está prestes a alterar ou excluir um registro histórico.<br>
            Isso afetará os indicadores e gráficos imediatamente.
        </div>
    """, unsafe_allow_html=True)
    
    st.write(f"**Data do Lançamento:** {pd.to_datetime(data_venda).strftime('%d/%m/%Y')}")
    
    # Campo para editar o valor
    novo_valor = st.number_input("Novo Valor da Venda (R$)", value=float(valor_atual), step=50.0)
    
    col_a, col_b = st.columns(2)
    
    with col_a:
        if st.button("💾 Atualizar Valor", use_container_width=True):
            if novo_valor > 0:
                try:
                    supabase.table("vendas_diarias").update({"valor_venda": novo_valor}).eq("id", id_venda).eq("company_id", cid).execute()
                    st.success("Registro atualizado!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao atualizar: {e}")
            else:
                st.warning("O valor deve ser positivo.")
    
    with col_b:
        if st.button("🗑️ Excluir Registro", type="primary", use_container_width=True):
            try:
                supabase.table("vendas_diarias").delete().eq("id", id_venda).eq("company_id", cid).execute()
                st.success("Registro excluído!")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao excluir: {e}")

# --- 4. FUNÇÕES DE NEGÓCIO ---

def init_session():
    if 'user' not in st.session_state: st.session_state.user = None
    if 'company' not in st.session_state: st.session_state.company = None
    if 'chat_history' not in st.session_state: st.session_state.chat_history = []

def login_user(email, password):
    try:
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.user = response.user
        st.success("Login realizado com sucesso!")
        time.sleep(1)
        st.rerun()
    except Exception as e:
        st.error(f"Erro no login: Verifique suas credenciais.")

def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.company = None
    st.session_state.chat_history = []
    st.rerun()

def get_user_companies(user_id):
    resp = supabase.table("company_users").select("company_id, companies(name)").eq("user_id", user_id).execute()
    companies = []
    if resp.data:
        for item in resp.data:
            companies.append({"id": item['company_id'], "name": item['companies']['name']})
    return companies

def create_company(user_id, company_name):
    try:
        res_comp = supabase.table("companies").insert({"name": company_name}).execute()
        new_company_id = res_comp.data[0]['id']
        # CRIA COM PERMISSÕES PADRÃO COMPLETAS PARA O ADMIN
        perm_padrao = ["Dashboard", "Extrato", "Metas", "Equipe", "Configurações"]
        supabase.table("company_users").insert({
            "user_id": user_id, 
            "company_id": new_company_id, 
            "role": "admin", 
            "permissions": json.dumps(perm_padrao)
        }).execute()
        st.success(f"Empresa {company_name} criada!")
        time.sleep(1)
        st.rerun()
    except Exception as e:
        st.error(f"Erro ao criar empresa: {e}")

def update_company_name(company_id, new_name):
    try:
        supabase.table("companies").update({"name": new_name}).eq("id", company_id).execute()
        st.session_state.company['name'] = new_name
        st.success("Nome atualizado!")
        time.sleep(1)
        st.rerun()
    except Exception as e:
        st.error(f"Erro ao atualizar: {e}")

# --- CORREÇÃO CRÍTICA AQUI: TRATAMENTO DE JSON/LISTA DO BANCO ---
def get_user_details(company_id, user_id):
    """Retorna o Role e a Lista de Permissões com tratamento de tipos"""
    try:
        resp = supabase.table("company_users").select("role, permissions").eq("company_id", company_id).eq("user_id", user_id).single().execute()
        if resp.data:
            role = resp.data['role'].strip().lower() # Garante que 'Admin ' vire 'admin'
            raw_perms = resp.data['permissions']
            
            # Verificação de tipo para evitar o erro do json.loads em lista
            if isinstance(raw_perms, list):
                perms = raw_perms
            elif isinstance(raw_perms, str):
                perms = json.loads(raw_perms)
            else:
                perms = ["Dashboard"] # Fallback
                
            return role, perms
        return 'viewer', ["Dashboard"]
    except:
        return 'viewer', ["Dashboard"]

def get_user_role(company_id, user_id):
    role, _ = get_user_details(company_id, user_id)
    return role

def update_user_permissions(company_id, user_id, new_perms):
    try:
        supabase.table("company_users").update({"permissions": json.dumps(new_perms)}).eq("company_id", company_id).eq("user_id", user_id).execute()
        return True
    except:
        return False

def get_config_dias(company_id):
    resp = supabase.table("config_dias_uteis").select("dias_trabalho").eq("company_id", company_id).execute()
    if resp.data: return json.loads(resp.data[0]['dias_trabalho'])
    return [0, 1, 2, 3, 4] 

def salvar_config_dias(company_id, lista_dias):
    payload = {"company_id": company_id, "dias_trabalho": json.dumps(lista_dias)}
    supabase.table("config_dias_uteis").upsert(payload, on_conflict="company_id").execute()

def get_feriados(company_id):
    feriados = supabase.table("feriados").select("*").eq("company_id", company_id).order("data").execute()
    return feriados.data

def calcular_dias_uteis(ano, mes, dias_trabalho, lista_feriados_datas):
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    data_ini = date(ano, mes, 1)
    data_fim = date(ano, mes, ultimo_dia)
    hoje = date.today()
    
    if hoje > data_fim: return 0
    
    weekmask_list = ['0'] * 7
    for dia in dias_trabalho: weekmask_list[dia] = '1'
    weekmask_str = "".join(weekmask_list)
    
    start_date = max(hoje, data_ini)
    if start_date > data_fim: return 0
    
    return np.busday_count(start_date.strftime('%Y-%m-%d'), data_fim.strftime('%Y-%m-%d'), weekmask=weekmask_str, holidays=lista_feriados_datas) + 1

# --- 5. TELA DASHBOARD ---
def render_dashboard(company_id):
    st.title(f"📊 Painel - {st.session_state.company['name']}")
    
    def format_moeda(valor):
        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    
    user_role = get_user_role(company_id, st.session_state.user.id)
    dias_trabalho = get_config_dias(company_id)
    feriados_raw = get_feriados(company_id)
    lista_feriados_datas = [f['data'] for f in feriados_raw]
    
    c_filtro1, c_filtro2, c_vazio = st.columns([1, 1, 2])
    hoje = date.today()
    
    with c_filtro1: 
        ano = st.selectbox("Ano", [2024, 2025, 2026], index=1, label_visibility="collapsed")
    with c_filtro2: 
        lista_meses = list(MESES_PT.values())
        idx_mes = hoje.month - 1 if hoje.month <= 12 else 0
        mes_nome = st.selectbox("Mês", lista_meses, index=idx_mes, label_visibility="collapsed")
        mes = lista_meses.index(mes_nome) + 1

    metas = supabase.table("metas").select("*").eq("company_id", company_id).eq("ano", ano).eq("mes", mes).execute()
    meta_val = metas.data[0]['meta_mensal'] if metas.data else 0
    
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    
    vendas = supabase.table("vendas_diarias").select("*").eq("company_id", company_id).gte("data_venda", f"{ano}-{mes:02d}-01").lte("data_venda", f"{ano}-{mes:02d}-{ultimo_dia}").order("data_venda").execute()
    
    df_vendas = pd.DataFrame(vendas.data)
    
    total_vendido = df_vendas['valor_venda'].sum() if not df_vendas.empty else 0
    percentual = (total_vendido / meta_val * 100) if meta_val > 0 else 0
    falta = max(0, meta_val - total_vendido)
    dias_uteis = calcular_dias_uteis(ano, mes, dias_trabalho, lista_feriados_datas)
    meta_diaria = falta / dias_uteis if dias_uteis > 0 else 0

    st.markdown("---")

    c_visual, c_input = st.columns([2, 1]) 

    with c_visual:
        col_g1, col_g2 = st.columns(2)
        chart_height = 220 
        
        with col_g1:
            max_gauge_value = meta_val if meta_val > 0 else 100
            
            fig_vendas = go.Figure(go.Indicator(
                mode = "gauge+number", value = total_vendido,
                title = {'text': "Total de Vendas", 'font': {'size': 14, 'color': '#0091EA'}},
                number = {'prefix': "R$ ", 'font': {'size': 30, 'color': '#0091EA'}}, 
                gauge = {
                    'axis': {'range': [0, max_gauge_value], 'tickwidth': 0}, 
                    'bar': {'color': "#0091EA"}, 
                    'bgcolor': "white", 
                    'borderwidth': 0, 
                    'steps': [{'range': [0, max_gauge_value], 'color': '#f0f2f6'}]
                }
            ))
            fig_vendas.update_layout(height=chart_height, margin=dict(l=20, r=20, t=60, b=10), separators=".,")
            st.plotly_chart(fig_vendas, use_container_width=True)
            
            st.markdown(f"""
                <div style="text-align: center; margin-top: -15px;">
                    <div style="font-size: 24px; font-weight: 900; color: #D32F2F;">{format_moeda(falta)}</div>
                    <div style="font-size: 14px; font-weight: bold; color: #FFFFFF; text-transform: uppercase;">Faltando p/ a Meta</div>
                </div>
            """, unsafe_allow_html=True)

        with col_g2:
            cor_meta = "#D32F2F" if percentual < 50 else "#FBC02D" if percentual < 100 else "#388E3C"
            fig_pct = go.Figure(go.Indicator(
                mode = "gauge+number", value = percentual,
                title = {'text': "% Meta Alcançada", 'font': {'size': 14, 'color': "#388E3C"}},
                number = {'suffix': "%", 'font': {'color': cor_meta, 'size': 30}},
                gauge = {'axis': {'range': [0, 100], 'tickwidth': 0}, 'bar': {'color': cor_meta}, 'bgcolor': "white", 'borderwidth': 0, 'steps': [{'range': [0, 100], 'color': '#f0f2f6'}]}
            ))
            fig_pct.update_layout(height=chart_height, margin=dict(l=20, r=20, t=60, b=10), separators=".,")
            st.plotly_chart(fig_pct, use_container_width=True)
            
            st.markdown(f"""
                <div style="text-align: center; margin-top: -15px;">
                    <div style="display: inline-block; margin-right: 15px; vertical-align: top; border-right: 1px solid #ccc; padding-right: 15px;">
                        <div style="font-size: 24px; font-weight: 900; color: #0091EA;">{format_moeda(meta_diaria)}</div>
                        <div style="font-size: 12px; font-weight: bold; color: #FFFFFF; text-transform: uppercase;">Meta Diária</div>
                    </div>
                    <div style="display: inline-block; vertical-align: top;">
                        <div style="font-size: 24px; font-weight: 900; color: #FFFFFF;">{dias_uteis}</div>
                        <div style="font-size: 12px; font-weight: bold; color: #FFFFFF; text-transform: uppercase;">Dias Úteis Restantes</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

    with c_input:
        if user_role in ['admin', 'data_entry']:
            with st.container(border=True):
                st.markdown("### 📝 Registrar Venda")
                
                with st.form("form_venda_rapida", clear_on_submit=True):
                    data_in = st.date_input("Data da Venda", value=hoje)
                    valor_in = st.number_input("Valor Total (R$)", min_value=0.0, step=50.0)
                    
                    if st.form_submit_button("💾 Salvar Venda", use_container_width=True):
                        if data_in > hoje:
                            alerta_data_futura() 
                        elif valor_in <= 0:
                            st.warning("⚠️ O valor deve ser maior que zero.")
                        else:
                            try:
                                payload = {
                                    "company_id": company_id,
                                    "data_venda": str(data_in),
                                    "valor_venda": valor_in
                                }
                                supabase.table("vendas_diarias").upsert(payload, on_conflict="company_id, data_venda").execute()
                                st.success(f"Venda Salva!")
                                time.sleep(1)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro: {e}")
        else:
            with st.container(border=True):
                 st.info("Acesso somente de visualização.")

    st.write("") 
    st.write("") 

    if not df_vendas.empty:
        full_month_days = pd.date_range(start=f"{ano}-{mes:02d}-01", end=f"{ano}-{mes:02d}-{ultimo_dia}", freq='D')
        df_full = pd.DataFrame(full_month_days, columns=['data_venda'])
        
        df_vendas['data_venda'] = pd.to_datetime(df_vendas['data_venda'])
        df_merged = pd.merge(df_full, df_vendas, on='data_venda', how='left').fillna(0)
        
        df_merged['valor_venda'] = np.where(df_merged['data_venda'].dt.date > hoje, np.nan, df_merged['valor_venda'])
        df_merged = df_merged.dropna(subset=['valor_venda'])
        
        df_merged['acumulado'] = df_merged['valor_venda'].cumsum()
        df_merged['dia_str'] = df_merged['data_venda'].dt.strftime('%d/%m')
        df_merged['label_acumulado'] = df_merged['acumulado'].apply(format_moeda)

        fig_combo = go.Figure()
        fig_combo.add_trace(go.Bar(
            x=df_merged['dia_str'], y=df_merged['acumulado'], name='Realizado Acumulado',
            marker_color='#1E88E5', text=df_merged['label_acumulado'], texttemplate='%{text}', textposition='outside'
        ))
        fig_combo.add_trace(go.Scatter(
            x=df_merged['dia_str'], y=[meta_val] * len(df_merged), name='Meta Mensal', 
            mode='lines', line=dict(color='red', width=2, dash='dash')
        ))
        fig_combo.update_layout(
            title={'text': "Evolução Acumulada vs Meta", 'y':0.9, 'x':0.5, 'xanchor': 'center', 'yanchor': 'top'},
            legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1),
            height=300, margin=dict(l=20, r=20, t=50, b=20),
            hovermode="x unified", plot_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(showgrid=False, showticklabels=False), xaxis=dict(showgrid=False), separators=".," 
        )
        st.plotly_chart(fig_combo, use_container_width=True)

        st.markdown("---")
        st.subheader("🤖 Analista Virtual")
        st.caption("Converse com seus dados. O chat mantém o histórico.")

        if st.button("🗑️ Limpar Conversa", key="clear_chat"):
            st.session_state.chat_history = []
            st.rerun()

        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input("Ex: 'Qual foi o melhor dia?'"):
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            with st.chat_message("user"): st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Analisando dados..."):
                    if "google" in st.secrets:
                        analista = GeminiAnalista(st.secrets["google"]["api_key"])
                        nome_empresa_atual = st.session_state.company['name']
                        resposta_ia = analista.analisar(df_vendas, prompt, nome_empresa_atual, st.session_state.chat_history)
                        st.markdown(resposta_ia)
                        st.session_state.chat_history.append({"role": "assistant", "content": resposta_ia})
                    else:
                        st.error("Configure a chave Google nos Secrets.")

    else:
        st.info("Sem dados neste mês.")

# --- 6. EXTRATO (COM DESTAQUE E EDIÇÃO) ---
def render_extrato(cid):
    st.title("📜 Extrato de Vendas")
    st.write("Acompanhe o detalhamento diário.")

    c1, c2, _ = st.columns([1, 1, 2])
    hoje = date.today()
    with c1: ano = st.selectbox("Ano", [2024, 2025, 2026], index=1, key="ext_a")
    with c2: 
        mn = st.selectbox("Mês", list(MESES_PT.values()), index=hoje.month-1, key="ext_m")
        mes = list(MESES_PT.values()).index(mn)+1
    
    ult = calendar.monthrange(ano, mes)[1]
    
    vendas = supabase.table("vendas_diarias").select("*").eq("company_id", cid).gte("data_venda", f"{ano}-{mes:02d}-01").lte("data_venda", f"{ano}-{mes:02d}-{ult}").execute().data
    
    if vendas:
        df = pd.DataFrame(vendas)
        df['data_venda'] = pd.to_datetime(df['data_venda']).dt.date
        
        df = df.sort_values(by='data_venda', ascending=False)
        
        max_val = df['valor_venda'].max()
        min_val = df['valor_venda'].min()
        
        def highlight_vals(row):
            s = [''] * len(row)
            if row['valor_venda'] == max_val:
                return ['background-color: #d4edda; color: #155724; font-weight: bold'] * len(row)
            elif row['valor_venda'] == min_val:
                return ['background-color: #f8d7da; color: #721c24; font-weight: bold'] * len(row)
            return s

        st.markdown("### 🗓️ Lançamentos")
        st.dataframe(
            df[['data_venda', 'valor_venda']].style.apply(highlight_vals, axis=1).format({"valor_venda": "R$ {:.2f}", "data_venda": "{:%d/%m/%Y}"}),
            use_container_width=True,
            hide_index=True,
            height=400
        )

        st.divider()
        st.subheader("🛠️ Gerenciar Lançamentos")
        st.caption("Selecione um lançamento abaixo para Editar ou Excluir.")
        
        opcoes = {f"{row['data_venda'].strftime('%d/%m')} - R$ {row['valor_venda']:.2f}": row['id'] for _, row in df.iterrows()}
        escolha = st.selectbox("Selecione o registro:", list(opcoes.keys()))
        
        if st.button("✏️ Editar / Excluir Selecionado"):
            id_sel = opcoes[escolha]
            dado_orig = df[df['id'] == id_sel].iloc[0]
            gerenciar_venda_dialog(id_sel, dado_orig['data_venda'], dado_orig['valor_venda'], cid)

    else:
        st.info(f"Sem lançamentos em {mn}/{ano}.")

# --- 7. TELAS AUXILIARES ---

def render_metas(company_id):
    user_role = get_user_role(company_id, st.session_state.user.id)
    if user_role not in ['admin']:
        st.warning("Você não tem permissão (Administrador).")
        return

    st.title("🎯 Definir Metas")
    metas_data = supabase.table("metas").select("*").eq("company_id", company_id).order("ano").order("mes").execute().data

    c1, c2 = st.columns([1, 2])
    with c1:
        with st.form("form_meta"):
            ano = st.number_input("Ano", 2024, 2030, 2025)
            mes_nome = st.selectbox("Mês", list(MESES_PT.values()))
            mes = list(MESES_PT.values()).index(mes_nome) + 1
            valor = st.number_input("Meta (R$)", min_value=0.0)
            if st.form_submit_button("Salvar"):
                supabase.table("metas").upsert({"company_id": company_id, "ano": ano, "mes": mes, "meta_mensal": valor}, on_conflict="company_id, ano, mes").execute()
                st.rerun()
    with c2:
        if metas_data:
            df = pd.DataFrame(metas_data)
            df['mes_nome'] = df['mes'].map(MESES_PT)
            st.dataframe(df[['ano', 'mes_nome', 'meta_mensal']].style.format({"meta_mensal": "R$ {:,.2f}"}), use_container_width=True, hide_index=True)


def render_config(company_id):
    user_role = get_user_role(company_id, st.session_state.user.id)
    if user_role not in ['admin']:
        st.warning("Você não tem permissão (Administrador).")
        return

    st.title("⚙️ Configurações")
    st.subheader("Dias de Trabalho")
    dias_atuais = get_config_dias(company_id)
    nomes = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    novos_dias = []
    cols = st.columns(7)
    for i, nome in enumerate(nomes):
        if cols[i].checkbox(nome, value=(i in dias_atuais)): novos_dias.append(i) 
    if st.button("Salvar Dias"):
        salvar_config_dias(company_id, novos_dias)
        st.success("Salvo!")
        st.rerun()

    st.divider()
    st.subheader("Feriados")
    c1, c2 = st.columns([1,2])
    with c1:
        with st.form("add_fer"):
            dt = st.date_input("Data")
            desc = st.text_input("Nome")
            if st.form_submit_button("Adicionar"):
                supabase.table("feriados").upsert({"company_id": company_id, "data": str(dt), "descricao": desc}, on_conflict="company_id, data").execute()
                st.rerun()
    with c2:
        feriados = get_feriados(company_id)
        if feriados:
            df = pd.DataFrame(feriados)
            df['data'] = pd.to_datetime(df['data']).dt.date
            edited = st.data_editor(df[['id', 'data', 'descricao']], hide_index=True, key="fer_edit", disabled=["id"], num_rows="dynamic")
            if st.button("Salvar Tabela"):
                ids_orig = set(df['id'])
                ids_new = set(edited['id'].dropna())
                to_del = ids_orig - ids_new
                if to_del: supabase.table("feriados").delete().in_("id", list(to_del)).execute()
                for row in edited.to_dict("records"):
                    p = {"company_id": company_id, "data": str(row['data']), "descricao": row['descricao']}
                    if pd.notna(row.get('id')): p['id'] = row['id']
                    supabase.table("feriados").upsert(p).execute()
                st.rerun()

def render_team(company_id):
    st.title("👥 Gestão de Equipe")
    user_role = get_user_role(company_id, st.session_state.user.id)
    
    if user_role == 'admin':
        with st.expander("➕ Adicionar Novo Membro", expanded=True):
            c1, c2 = st.columns([3, 1])
            with c1:
                email_invite = st.text_input("E-mail do usuário")
            with c2:
                st.write(""); st.write("") 
                if st.button("Adicionar"):
                    user_uuid = supabase.rpc("get_user_id_by_email", {"user_email": email_invite}).execute()
                    if user_uuid.data and user_uuid.data[0]:
                        try:
                            # Cria com permissão padrão (Dashboard)
                            perm_padrao = ["Dashboard"]
                            supabase.table("company_users").insert({
                                "company_id": company_id, 
                                "user_id": user_uuid.data[0], 
                                "role": "viewer",
                                "permissions": json.dumps(perm_padrao)
                            }).execute()
                            st.success(f"Usuário {email_invite} adicionado!")
                            time.sleep(1); st.rerun()
                        except: st.error("Erro: Usuário já existe ou falha no sistema.")
                    else: st.error("E-mail não encontrado.")

    st.divider()
    st.subheader("Membros e Permissões")
    members = supabase.rpc("get_team_members", {"cid": company_id}).execute()
    
    telas_disponiveis = ["Dashboard", "Extrato", "Metas", "Equipe", "Configurações"]

    if members.data:
        for m in members.data:
            with st.container(border=True):
                c_email, c_role, c_perms, c_action = st.columns([1.5, 1, 2, 0.5])
                
                with c_email:
                    st.write(f"📧 **{m['email']}**")
                
                with c_role:
                    if m['user_id'] == st.session_state.user.id or user_role != 'admin':
                        st.info(m['role'].upper())
                    else:
                        roles = ['admin', 'data_entry', 'viewer']
                        nr = st.selectbox("Função", roles, index=roles.index(m['role']), key=f"r_{m['user_id']}", label_visibility="collapsed")
                        if nr != m['role']:
                            supabase.table("company_users").update({"role": nr}).eq("user_id", m['user_id']).eq("company_id", company_id).execute()
                            st.rerun()
                
                with c_perms:
                    curr_p_raw = supabase.table("company_users").select("permissions").eq("user_id", m['user_id']).eq("company_id", company_id).single().execute()
                    # CORREÇÃO AQUI: Verifica se é lista ou string
                    if curr_p_raw.data and curr_p_raw.data['permissions']:
                        if isinstance(curr_p_raw.data['permissions'], list):
                            curr_p = curr_p_raw.data['permissions']
                        else:
                            curr_p = json.loads(curr_p_raw.data['permissions'])
                    else:
                        curr_p = ["Dashboard"]
                    
                    if user_role == 'admin' and m['user_id'] != st.session_state.user.id:
                        new_perms = st.multiselect("Acessos", telas_disponiveis, default=curr_p, key=f"p_{m['user_id']}", label_visibility="collapsed")
                        if new_perms != curr_p:
                            update_user_permissions(company_id, m['user_id'], new_perms)
                            st.toast("Permissões atualizadas!")
                    else:
                        st.caption(", ".join(curr_p))

                with c_action:
                    if m['user_id'] != st.session_state.user.id and user_role == 'admin':
                        if st.button("🗑️", key=f"d_{m['user_id']}"):
                            supabase.table("company_users").delete().eq("user_id", m['user_id']).eq("company_id", company_id).execute()
                            st.rerun()

# --- 8. TELAS DE LOGIN/SELEÇÃO ---

def render_login_screen():
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<h2 style='text-align: center;'>🔐 Acesso ao Sistema</h2>", unsafe_allow_html=True)
        tab1, tab2 = st.tabs(["Login", "Criar Conta"])
        with tab1:
            with st.form("login_f"):
                email = st.text_input("Email")
                senha = st.text_input("Senha", type="password")
                if st.form_submit_button("Entrar"): login_user(email, senha)
        with tab2:
            with st.form("reg_f"):
                email = st.text_input("Email")
                senha = st.text_input("Senha", type="password")
                if st.form_submit_button("Cadastrar"): 
                    try:
                        r = supabase.auth.sign_up({"email": email, "password": senha})
                        if r.user: st.success("Conta criada! Confirme seu email.")
                    except Exception as e: st.error(f"Erro: {e}")

def render_company_selector(user_id):
    st.title("🏢 Empresas")
    companies = get_user_companies(user_id)
    if not companies:
        st.warning("Nenhuma empresa.")
        with st.form("new_c"):
            name = st.text_input("Nome da Empresa")
            if st.form_submit_button("Criar"): create_company(user_id, name)
    else:
        opts = {c['name']: c['id'] for c in companies}
        sel = st.selectbox("Escolha:", list(opts.keys()))
        if st.button("Acessar Painel"):
            st.session_state.company = {'id': opts[sel], 'name': sel}
            st.rerun()
        st.divider()
        with st.expander("Nova Empresa"):
            with st.form("add_c"):
                n = st.text_input("Nome"); 
                if st.form_submit_button("Criar"): create_company(user_id, n)

@st.dialog("✏️ Editar")
def open_edit_company_dialog(company_id, current_name):
    new_name = st.text_input("Nome", value=current_name)
    if st.button("Salvar"): update_company_name(company_id, new_name)

# --- 9. EXECUÇÃO PRINCIPAL ---
init_session()

if st.session_state.user is None:
    render_login_screen()
elif st.session_state.company is None:
    if st.sidebar.button("Sair"): # Fix do Callback
        logout()
    render_company_selector(st.session_state.user.id)
else:
    # 1. Busca Role e Permissões do Usuário Logado
    current_role, current_perms = get_user_details(st.session_state.company['id'], st.session_state.user.id)
    
    with st.sidebar:
        c1, c2 = st.columns([0.8, 0.2])
        with c1:
            st.write("Empresa:")
            st.markdown(f"**{st.session_state.company['name']}**")
        with c2:
            if st.button("✏️"): open_edit_company_dialog(st.session_state.company['id'], st.session_state.company['name'])
        
        st.divider()
        if st.button("🔄 Trocar"):
            st.session_state.company = None
            st.rerun()
            
        # 2. Monta o Menu Dinâmico com base nas permissões do banco
        if current_role == 'admin':
            menu_opts = ["Dashboard", "Extrato", "Metas", "Equipe", "Configurações"]
        else:
            menu_opts = current_perms
            
        menu = st.radio("Navegação", menu_opts)
        
        st.divider()
        if st.button("🚪 Sair"): # Fix do Callback e Indentação
            logout()

    comp_id = st.session_state.company['id']
    
    # 3. Roteamento (Renderiza apenas o que foi escolhido no menu)
    if menu == "Dashboard": render_dashboard(comp_id)
    elif menu == "Extrato": render_extrato(comp_id)
    elif menu == "Metas": render_metas(comp_id)
    elif menu == "Equipe": render_team(comp_id, current_role) # Passa role para Equipe
    elif menu == "Configurações": render_config(comp_id)
