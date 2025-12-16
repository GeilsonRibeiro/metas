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

# --- 1. CONFIGURAÇÃO GERAL ---
st.set_page_config(page_title="Gestão de Metas", layout="wide", page_icon="🚀")

# CSS e Estilos
st.markdown("""
<style>
    .metric-card { background-color: #f0f2f6; border-radius: 10px; padding: 20px; text-align: center; box-shadow: 2px 2px 5px rgba(0,0,0,0.1); }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# Dicionário de Meses
MESES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto", 
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
}

# --- 2. CONEXÃO SUPABASE ---
@st.cache_resource
def init_connection():
    # As credenciais são lidas do arquivo .streamlit/secrets.toml
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = init_connection()

# --- 3. SISTEMA DE LOGIN E SESSÃO ---

def init_session():
    if 'user' not in st.session_state: st.session_state.user = None
    if 'company' not in st.session_state: st.session_state.company = None

def login_user(email, password):
    try:
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.user = response.user
        st.success("Login realizado!")
        time.sleep(1)
        st.rerun()
    except Exception as e:
        st.error(f"Erro no login: {e}")

def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.company = None
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
        supabase.table("company_users").insert({"user_id": user_id, "company_id": new_company_id, "role": "admin"}).execute()
        st.success(f"Empresa {company_name} criada!")
        time.sleep(1)
        st.rerun()
    except Exception as e:
        st.error(f"Erro: {e}")

def update_company_name(company_id, new_name):
    try:
        supabase.table("companies").update({"name": new_name}).eq("id", company_id).execute()
        st.session_state.company['name'] = new_name
        st.success("Nome atualizado!")
        time.sleep(1)
        st.rerun()
    except Exception as e:
        st.error(f"Erro ao atualizar: {e}")

def get_user_role(company_id, user_id):
    """Busca o papel (role) do usuário na empresa ativa."""
    try:
        resp = supabase.table("company_users").select("role").eq("company_id", company_id).eq("user_id", user_id).single().execute()
        return resp.data['role'] if resp.data else 'viewer'
    except Exception:
        return 'viewer'


# --- 4. FUNÇÕES DE NEGÓCIO (COM COMPANY_ID) ---

def get_config_dias(company_id):
    resp = supabase.table("config_dias_uteis").select("dias_trabalho").eq("company_id", company_id).execute()
    if resp.data: return json.loads(resp.data[0]['dias_trabalho'])
    return [0, 1, 2, 3, 4] # Padrão: Seg a Sex

def salvar_config_dias(company_id, lista_dias):
    payload = {
        "company_id": company_id,
        "dias_trabalho": json.dumps(lista_dias)
    }
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
    
    return np.busday_count(start_date.strftime('%Y-%m-%d'), data_fim.strftime('%Y-%m-%d'), weekmask=weekmask_str, holidays=lista_feriados_datas) + 1 # +1 para incluir o dia atual se for útil


# --- 5. TELA DASHBOARD ---
def render_dashboard(company_id):
    st.title(f"📊 Painel - {st.session_state.company['name']}")
    
    def format_moeda(valor):
        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    
    user_role = get_user_role(company_id, st.session_state.user.id)
    
    # 1. Filtros e Dados
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

    # Busca Dados (COM COMPANY_ID)
    metas = supabase.table("metas").select("*").eq("company_id", company_id).eq("ano", ano).eq("mes", mes).execute()
    meta_val = metas.data[0]['meta_mensal'] if metas.data else 0
    
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    
    # LINHA 171: CORREÇÃO MINIMA: apenas o nome da coluna para usar o padrão ASC e evitar o erro de 3 argumentos/parsing.
    vendas = supabase.table("vendas_diarias").select("*").eq("company_id", company_id).gte("data_venda", f"{ano}-{mes:02d}-01").lte("data_venda", f"{ano}-{mes:02d}-{ultimo_dia}").order("data_venda").execute()
    
    df_vendas = pd.DataFrame(vendas.data)
    
    # Cálculos
    total_vendido = df_vendas['valor_venda'].sum() if not df_vendas.empty else 0
    percentual = (total_vendido / meta_val * 100) if meta_val > 0 else 0
    falta = max(0, meta_val - total_vendido)
    dias_uteis = calcular_dias_uteis(ano, mes, dias_trabalho, lista_feriados_datas)
    meta_diaria = falta / dias_uteis if dias_uteis > 0 else 0

    st.markdown("---")

    # --- LAYOUT DE COCKPIT ---
    c_visual, c_input = st.columns([2, 1]) 

    with c_visual:
        col_g1, col_g2 = st.columns(2)
        chart_height = 220 
        
        # Gauge 1: Vendas
        with col_g1:
            fig_vendas = go.Figure(go.Indicator(
                mode = "gauge+number", value = total_vendido,
                title = {'text': "Total de Vendas", 'font': {'size': 14, 'color': '#0091EA'}},
                number = {'prefix': "R$ ", 'font': {'size': 20, 'color': '#0091EA'}}, 
                gauge = {'axis': {'range': [None, meta_val], 'tickwidth': 0}, 'bar': {'color': "#0091EA"}, 'bgcolor': "white", 'borderwidth': 0, 'steps': [{'range': [0, meta_val], 'color': '#f0f2f6'}]}
            ))
            fig_vendas.update_layout(height=chart_height, margin=dict(l=20, r=20, t=60, b=10), separators=".,")
            st.plotly_chart(fig_vendas, use_container_width=True)
            
            st.markdown(f"""
                <div style="text-align: center; margin-top: -15px;">
                    <div style="font-size: 24px; font-weight: 900; color: #D32F2F;">{format_moeda(falta)}</div>
                    <div style="font-size: 14px; font-weight: bold; color: #000000; text-transform: uppercase;">Faltando p/ a Meta</div>
                </div>
            """, unsafe_allow_html=True)

        # Gauge 2: % e Dias
        with col_g2:
            cor_meta = "#D32F2F" if percentual < 50 else "#FBC02D" if percentual < 100 else "#388E3C"
            fig_pct = go.Figure(go.Indicator(
                mode = "gauge+number", value = percentual,
                title = {'text': "% Meta Alcançada", 'font': {'size': 14, 'color': 'black'}},
                number = {'suffix': "%", 'font': {'color': cor_meta, 'size': 20}},
                gauge = {'axis': {'range': [0, 100], 'tickwidth': 0}, 'bar': {'color': cor_meta}, 'bgcolor': "white", 'borderwidth': 0, 'steps': [{'range': [0, 100], 'color': '#f0f2f6'}]}
            ))
            fig_pct.update_layout(height=chart_height, margin=dict(l=20, r=20, t=60, b=10), separators=".,")
            st.plotly_chart(fig_pct, use_container_width=True)
            
            st.markdown(f"""
                <div style="text-align: center; margin-top: -15px;">
                    <div style="display: inline-block; margin-right: 15px; vertical-align: top; border-right: 1px solid #ccc; padding-right: 15px;">
                        <div style="font-size: 24px; font-weight: 900; color: #0091EA;">{format_moeda(meta_diaria)}</div>
                        <div style="font-size: 12px; font-weight: bold; color: #000000; text-transform: uppercase;">Meta Diária</div>
                    </div>
                    <div style="display: inline-block; vertical-align: top;">
                        <div style="font-size: 24px; font-weight: 900; color: #333;">{dias_uteis}</div>
                        <div style="font-size: 12px; font-weight: bold; color: #000000; text-transform: uppercase;">Dias Úteis Restantes</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

    # --- INPUT DE VENDAS (DIREITA) ---
    with c_input:
        
        if user_role in ['admin', 'data_entry']:
            with st.container(border=True):
                st.markdown("### 📝 Registrar Venda")
                st.write("Lance o total vendido no dia.")
                
                with st.form("form_venda_rapida", clear_on_submit=True):
                    data_in = st.date_input("Data da Venda", value=hoje)
                    valor_in = st.number_input("Valor Total (R$)", min_value=0.0, step=50.0)
                    
                    if st.form_submit_button("💾 Salvar Venda", use_container_width=True):
                        if valor_in > 0:
                            try:
                                payload = {
                                    "company_id": company_id,
                                    "data_venda": str(data_in),
                                    "valor_venda": valor_in
                                }
                                # Usa UPSERT: Se a data já existir, atualiza. Se não, insere.
                                supabase.table("vendas_diarias").upsert(payload, on_conflict="company_id, data_venda").execute()
                                st.success(f"Venda Salva!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro: {e}")
                        else:
                            st.warning("Valor deve ser maior que zero.")
        else:
            # Mensagem para quem só pode visualizar (viewer)
            with st.container(border=True):
                 st.info("Acesso somente de visualização. Apenas administradores ou usuários de lançamento de dados podem registrar novas vendas.")

    st.write("") 
    st.write("") 

    # --- GRÁFICO ACUMULADO ---
    if not df_vendas.empty:
        # Cria a coluna de datas completas do mês para o gráfico de linha de meta
        full_month_days = pd.date_range(start=f"{ano}-{mes:02d}-01", end=f"{ano}-{mes:02d}-{ultimo_dia}", freq='D')
        df_full = pd.DataFrame(full_month_days, columns=['data_venda'])
        
        # Merge com os dados de vendas
        df_vendas['data_venda'] = pd.to_datetime(df_vendas['data_venda'])
        df_merged = pd.merge(df_full, df_vendas, on='data_venda', how='left').fillna(0)
        
        # Remove dias futuros não úteis para não estragar a linha de meta
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
    else:
        st.info(f"Sem dados em {mes_nome}/{ano}.")


# --- 6. TELAS AUXILIARES ---

def render_metas(company_id):
    # --- RBAC: Apenas Admin pode definir metas ---
    user_role = get_user_role(company_id, st.session_state.user.id)
    if user_role not in ['admin']:
        st.warning("Você não tem permissão (Administrador) para definir metas.")
        return
    # ----------------------------------------------

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
    # --- RBAC: Apenas Admin pode configurar ---
    user_role = get_user_role(company_id, st.session_state.user.id)
    if user_role not in ['admin']:
        st.warning("Você não tem permissão (Administrador) para alterar configurações.")
        return
    # -----------------------------------------

    st.title("⚙️ Configurações")
    st.subheader("Dias de Trabalho")
    dias_atuais = get_config_dias(company_id)
    nomes = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    novos_dias = []
    cols = st.columns(7)
    for i, nome in enumerate(nomes):
        # A API do Numpy (busday) usa 0=Seg, 6=Dom
        if cols[i].checkbox(nome, value=(i in dias_atuais)): novos_dias.append(i) 
    if st.button("Salvar Dias"):
        salvar_config_dias(company_id, novos_dias)
        st.success("Salvo!")
        st.cache_resource.clear()
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
    st.write("Gerencie quem tem acesso aos dados desta empresa.")

    my_role = get_user_role(company_id, st.session_state.user.id)
    
    # 1. Formulário para Adicionar Membro (Visível apenas para Admin)
    if my_role == 'admin':
        with st.expander("➕ Adicionar Novo Membro", expanded=True):
            c1, c2 = st.columns([3, 1])
            with c1:
                email_invite = st.text_input("E-mail do usuário (ele precisa ter cadastro no sistema)")
            with c2:
                st.write("") 
                st.write("") 
                if st.button("Adicionar"):
                    # Busca o ID desse email via RPC
                    user_uuid = supabase.rpc("get_user_id_by_email", {"user_email": email_invite}).execute()
                    
                    if user_uuid.data and user_uuid.data[0]:
                        found_id = user_uuid.data[0]
                        try:
                            # Insere na tabela de vínculo
                            supabase.table("company_users").insert({
                                "company_id": company_id,
                                "user_id": found_id,
                                "role": "viewer" # Padrão: Visualizador
                            }).execute()
                            st.success(f"{email_invite} adicionado com sucesso!")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error("Usuário já está na equipe ou ocorreu um erro. (Verifique se já foi adicionado)")
                    else:
                        st.error("E-mail não encontrado. Peça para o usuário criar uma conta no sistema primeiro.")

    st.divider()

    # 2. Lista de Membros
    st.subheader("Membros Atuais")
    
    members = supabase.rpc("get_team_members", {"cid": company_id}).execute()
    
    if members.data:
        for m in members.data:
            with st.container(border=True):
                c_email, c_role, c_action = st.columns([2, 1, 1])
                
                with c_email:
                    st.write(f"📧 **{m['email']}**")
                    if m['user_id'] == st.session_state.user.id: st.caption("👑 (Você)")
                
                with c_role:
                    # Permite alterar o papel APENAS se você for admin E não for você mesmo
                    if m['user_id'] == st.session_state.user.id or my_role != 'admin':
                        st.info(m['role'].upper())
                    else:
                        # Dropdown para mudar o papel
                        role_options = ['admin', 'data_entry', 'viewer']
                        new_role = st.selectbox("Papel", role_options, index=role_options.index(m['role']), key=f"role_{m['user_id']}", label_visibility="collapsed")
                        if new_role != m['role']:
                            try:
                                supabase.table("company_users").update({"role": new_role}).eq("user_id", m['user_id']).eq("company_id", company_id).execute()
                                st.success(f"Papel de {m['email']} atualizado para {new_role}!")
                                time.sleep(1)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Erro ao salvar: {e}")

                with c_action:
                    # Permite remover APENAS se você for admin E não for você mesmo
                    if m['user_id'] != st.session_state.user.id and my_role == 'admin':
                        if st.button("Remover", key=f"del_{m['user_id']}"):
                            supabase.table("company_users").delete().eq("user_id", m['user_id']).eq("company_id", company_id).execute()
                            st.success("Removido!")
                            time.sleep(1)
                            st.rerun()
                    else:
                        st.write("") 
    else:
        st.info("Nenhum membro encontrado.")


# --- 7. TELAS DE LOGIN/SELEÇÃO ---

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
                        if r.user: st.success("Conta criada! Verifique seu email para confirmar e faça login.")
                    except Exception as e: st.error(f"Erro: {e}")

def render_company_selector(user_id):
    st.title("🏢 Selecione a Empresa")
    companies = get_user_companies(user_id)
    if not companies:
        st.warning("Nenhuma empresa encontrada.")
        with st.form("new_c"):
            name = st.text_input("Nome da Empresa")
            if st.form_submit_button("Criar Nova"): create_company(user_id, name)
    else:
        opts = {c['name']: c['id'] for c in companies}
        sel = st.selectbox("Escolha o painel:", list(opts.keys()))
        if st.button("Acessar Painel"):
            st.session_state.company = {'id': opts[sel], 'name': sel}
            st.rerun()
        st.divider()
        with st.expander("Cadastrar outra empresa"):
            with st.form("add_c"):
                n = st.text_input("Nome"); 
                if st.form_submit_button("Criar"): create_company(user_id, n)

@st.dialog("✏️ Editar Dados da Empresa")
def open_edit_company_dialog(company_id, current_name):
    st.write("Altere o nome da sua empresa.")
    new_name = st.text_input("Nome da Empresa", value=current_name)
    if st.button("💾 Salvar Alterações"):
        if new_name:
            update_company_name(company_id, new_name)
        else:
            st.warning("O nome não pode ficar vazio.")

# --- 8. EXECUÇÃO PRINCIPAL ---
init_session()

if st.session_state.user is None:
    render_login_screen()
elif st.session_state.company is None:
    st.sidebar.button("Sair", on_click=logout)
    render_company_selector(st.session_state.user.id)
else:
    # SISTEMA LOGADO E EMPRESA SELECIONADA
    with st.sidebar:
        # CABEÇALHO DA EMPRESA COM BOTÃO DE EDITAR
        col_name, col_edit = st.columns([0.8, 0.2])
        
        with col_name:
            st.write("Empresa:")
            st.markdown(f"**{st.session_state.company['name']}**")
            
        with col_edit:
            if st.button("✏️", help="Editar nome da empresa"):
                open_edit_company_dialog(st.session_state.company['id'], st.session_state.company['name'])
        
        st.divider()
        
        # RESTO DO MENU
        if st.button("🔄 Trocar Empresa"):
            st.session_state.company = None
            st.rerun()
            
        menu = st.radio("Navegação", ["Dashboard", "Metas", "Equipe", "Configurações"])
        
        st.divider()
        st.button("🚪 Sair", on_click=logout)

    comp_id = st.session_state.company['id']
    if menu == "Dashboard": render_dashboard(comp_id)
    elif menu == "Metas": render_metas(comp_id)
    elif menu == "Equipe": render_team(comp_id)
    elif menu == "Configurações": render_config(comp_id)