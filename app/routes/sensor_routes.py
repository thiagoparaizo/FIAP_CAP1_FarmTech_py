# app/routes/sensor_routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from app.services.sql_db_service import SQLDatabaseService
from app.services.db_service import DatabaseService
from datetime import datetime, timedelta

sensor_bp = Blueprint('sensores', __name__)

# Obter instâncias de serviço
def get_sql_db():
    return SQLDatabaseService(current_app.config['SQL_DATABASE_URI'])

def get_mongo_db():
    return DatabaseService(current_app.config['MONGO_URI'])

# Rotas web para sensores
@sensor_bp.route('/')
def index():
    """Página principal de sensores"""
    sql_db = get_sql_db()
    mongo_db = get_mongo_db()
    
    # Obter todos os sensores ativos
    sensores = []
    session = sql_db.get_session()
    try:
        from app.models.sensor_models import Sensor
        from sqlalchemy.orm import joinedload
        #sensores = session.query(Sensor).filter_by(ativo=True).all()
        sensores = session.query(Sensor).options(joinedload(Sensor.posicao)).filter_by(ativo=True).all()
    finally:
        session.close()
    
    # Obter todos os campos para referenciar
    campos = mongo_db.obter_todos_campos()
    
    return render_template('sensores/index.html', 
                          sensores=sensores, 
                          campos=campos, 
                          total_sensores=len(sensores))

@sensor_bp.route('/sensor/<int:sensor_id>')
def detalhe_sensor(sensor_id):
    """Página de detalhes de um sensor"""
    sql_db = get_sql_db()
    
    # Obter sensor e sua posição
    sensor = sql_db.obter_sensor(sensor_id)
    if not sensor:
        flash('Sensor não encontrado', 'danger')
        return redirect(url_for('sensores.index'))
    
    # Obter as últimas leituras
    leituras = sql_db.obter_leituras_por_sensor(sensor_id, limite=50)
    
    # Calcular estatísticas dos últimos 7 dias
    data_fim = datetime.now()
    data_inicio = data_fim - timedelta(days=7)
    estatisticas = sql_db.calcular_estatisticas_leituras(sensor_id, data_inicio, data_fim)
    
    # Obter alertas ativos
    session = sql_db.get_session()
    alertas = []
    try:
        from app.models.sensor_models import AlertaSensor
        alertas = session.query(AlertaSensor).filter_by(
            sensor_id=sensor_id, 
            resolvido=False
        ).order_by(AlertaSensor.data_hora.desc()).all()
    finally:
        session.close()
    
    # Se for um sensor instalado em um campo, obter informações do campo
    campo = None
    if hasattr(sensor, 'posicao') and sensor.posicao and sensor.posicao.campo_id:
        mongo_db = get_mongo_db()
        campo = mongo_db.obter_campo_por_id(sensor.posicao.campo_id)
    
    return render_template('sensores/detalhe_sensor.html', 
                          sensor=sensor, 
                          leituras=leituras, 
                          estatisticas=estatisticas,
                          alertas=alertas,
                          campo=campo)

@sensor_bp.route('/adicionar', methods=['GET', 'POST'])
def adicionar_sensor():
    """Adicionar um novo sensor"""
    if request.method == 'POST':
        tipo = request.form.get('tipo')
        modelo = request.form.get('modelo')
        campo_id = request.form.get('campo_id')
        latitude = request.form.get('latitude')
        longitude = request.form.get('longitude')
        profundidade = request.form.get('profundidade')
        
        try:
            latitude = float(latitude) if latitude else None
            longitude = float(longitude) if longitude else None
            profundidade = float(profundidade) if profundidade else None
            
            sql_db = get_sql_db()
            
            # Adicionar sensor
            sensor_id = sql_db.adicionar_sensor(tipo, modelo)
            
            # Se tiver campo_id, adicionar posição
            if campo_id:
                sql_db.adicionar_posicao_sensor(
                    sensor_id, 
                    campo_id, 
                    latitude, 
                    longitude, 
                    profundidade
                )
            
            flash('Sensor adicionado com sucesso!', 'success')
            return redirect(url_for('sensores.detalhe_sensor', sensor_id=sensor_id))
        except Exception as e:
            flash(f'Erro ao adicionar sensor: {str(e)}', 'danger')
    
    # GET: mostrar formulário
    mongo_db = get_mongo_db()
    campos = mongo_db.obter_todos_campos()
    
    return render_template('sensores/sensor_form.html', campos=campos)

@sensor_bp.route('/campo/<campo_id>')
def sensores_por_campo(campo_id):
    """Lista de sensores em um campo específico"""
    sql_db = get_sql_db()
    mongo_db = get_mongo_db()
    
    # Obter campo
    campo = mongo_db.obter_campo_por_id(campo_id)
    if not campo:
        flash('Campo não encontrado', 'danger')
        return redirect(url_for('sensores.index'))
    
    # Obter sensores do campo
    sensores = sql_db.obter_sensores_por_campo(campo_id)
    
    return render_template('sensores/sensores_campo.html', 
                          sensores=sensores, 
                          campo=campo)

@sensor_bp.route('/registrar-leitura', methods=['POST'])
def registrar_leitura():
    """Registra uma nova leitura de sensor (via formulário ou API)"""
    if request.content_type == 'application/json':
        data = request.json
    else:
        data = request.form
    
    sensor_id = data.get('sensor_id')
    valor = data.get('valor')
    unidade = data.get('unidade')
    
    if not all([sensor_id, valor, unidade]):
        if request.content_type == 'application/json':
            return jsonify({"erro": "Dados incompletos"}), 400
        else:
            flash('Dados incompletos', 'danger')
            return redirect(url_for('sensores.index'))
    
    try:
        sql_db = get_sql_db()
        sql_db.adicionar_leitura(
            int(sensor_id), 
            float(valor), 
            unidade
        )
        
        if request.content_type == 'application/json':
            return jsonify({"mensagem": "Leitura registrada com sucesso"}), 201
        else:
            flash('Leitura registrada com sucesso!', 'success')
            return redirect(url_for('sensores.detalhe_sensor', sensor_id=sensor_id))
    except Exception as e:
        if request.content_type == 'application/json':
            return jsonify({"erro": str(e)}), 500
        else:
            flash(f'Erro ao registrar leitura: {str(e)}', 'danger')
            return redirect(url_for('sensores.detalhe_sensor', sensor_id=sensor_id))

# API para recomendações
@sensor_bp.route('/api/analisar-campo/<campo_id>', methods=['GET'])
def analisar_campo(campo_id):
    """Analisa os dados dos sensores de um campo e gera recomendações"""
    sql_db = get_sql_db()
    mongo_db = get_mongo_db()
    
    # Verificar se o campo existe
    campo = mongo_db.obter_campo_por_id(campo_id)
    if not campo:
        return jsonify({"erro": "Campo não encontrado"}), 404
    
    # Obter todos os sensores do campo
    sensores = sql_db.obter_sensores_por_campo(campo_id)
    if not sensores:
        return jsonify({"erro": "Nenhum sensor encontrado no campo"}), 404
    
    # Analisar dados de cada tipo de sensor
    resultado = {"campo_id": campo_id, "recomendacoes": []}
    
    # 1. Sensor de umidade (S1)
    sensores_umidade = [s for s in sensores if s.tipo == 'S1']
    if sensores_umidade:
        for sensor in sensores_umidade:
            # Obter últimas leituras
            leituras = sql_db.obter_leituras_por_sensor(sensor.id, limite=10)
            if leituras:
                # Calcular média das últimas leituras
                media_umidade = sum(l.valor for l in leituras) / len(leituras)
                
                # Verificar se precisa de irrigação
                if media_umidade < 30:  # Valor exemplo, ajustar conforme necessidade
                    # Calcular quantidade de água recomendada
                    area_hectare = campo.get('campo', {}).get('area_total_hectare', 0)
                    agua_recomendada = (30 - media_umidade) * area_hectare * 1000  # Litros
                    
                    recomendacao_id = sql_db.adicionar_recomendacao(
                        campo_id,
                        "água",
                        agua_recomendada,
                        "L",
                        f"Média de umidade: {media_umidade}% - Abaixo do ideal (30%)"
                    )
                    
                    resultado["recomendacoes"].append({
                        "id": recomendacao_id,
                        "tipo": "irrigação",
                        "quantidade": agua_recomendada,
                        "unidade": "L",
                        "motivo": f"Umidade média de {media_umidade:.1f}% está abaixo do ideal"
                    })
    
   # 2. Sensor de pH (S2)
    sensores_ph = [s for s in sensores if s.tipo == 'S2']
    if sensores_ph:
        for sensor in sensores_ph:
            # Obter últimas leituras
            leituras = sql_db.obter_leituras_por_sensor(sensor.id, limite=10)
            if leituras:
                # Calcular média das últimas leituras
                media_ph = sum(l.valor for l in leituras) / len(leituras)
                
                # Obter os valores ideais de pH da cultura plantada
                cultura_nome = campo.get('campo', {}).get('cultura_plantada', '')
                cultura = mongo_db.obter_cultura_por_nome(cultura_nome) if cultura_nome else None
                
                if cultura:
                    ph_min = cultura.get('clima_solo', {}).get('ph_ideal', {}).get('minimo', 0)
                    ph_max = cultura.get('clima_solo', {}).get('ph_ideal', {}).get('maximo', 0)
                    
                    # Verificar se o pH está fora do ideal
                    if media_ph < ph_min:
                        # Recomendar calagem (aumentar pH)
                        area_hectare = campo.get('campo', {}).get('area_total_hectare', 0)
                        calagem_recomendada = (ph_min - media_ph) * area_hectare * 500  # kg de calcário por hectare
                        
                        recomendacao_id = sql_db.adicionar_recomendacao(
                            campo_id,
                            "calcário",
                            calagem_recomendada,
                            "kg",
                            f"pH médio: {media_ph} - Abaixo do ideal ({ph_min}-{ph_max})"
                        )
                        
                        resultado["recomendacoes"].append({
                            "id": recomendacao_id,
                            "tipo": "calagem",
                            "quantidade": calagem_recomendada,
                            "unidade": "kg",
                            "motivo": f"pH médio de {media_ph:.1f} está abaixo do ideal ({ph_min:.1f}-{ph_max:.1f})"
                        })
                    elif media_ph > ph_max:
                        # Recomendar aplicação de enxofre (diminuir pH)
                        area_hectare = campo.get('campo', {}).get('area_total_hectare', 0)
                        enxofre_recomendado = (media_ph - ph_max) * area_hectare * 300  # kg de enxofre por hectare
                        
                        recomendacao_id = sql_db.adicionar_recomendacao(
                            campo_id,
                            "enxofre",
                            enxofre_recomendado,
                            "kg",
                            f"pH médio: {media_ph} - Acima do ideal ({ph_min}-{ph_max})"
                        )
                        
                        resultado["recomendacoes"].append({
                            "id": recomendacao_id,
                            "tipo": "aplicação de enxofre",
                            "quantidade": enxofre_recomendado,
                            "unidade": "kg",
                            "motivo": f"pH médio de {media_ph:.1f} está acima do ideal ({ph_min:.1f}-{ph_max:.1f})"
                        })
    
    # 3. Sensor de nutrientes (S3)
    sensores_nutrientes = [s for s in sensores if s.tipo == 'S3']
    if sensores_nutrientes:
        for sensor in sensores_nutrientes:
            # Obter últimas leituras - assumindo que são enviadas como JSON
            # Exemplo: {"P": 12.5, "K": 8.3}
            leituras = sql_db.obter_leituras_por_sensor(sensor.id, limite=10)
            if leituras:
                # Extrair os valores de P e K das leituras
                valores_p = []
                valores_k = []
                
                for leitura in leituras:
                    try:
                        import json
                        # Verificar se o valor é um JSON válido
                        nutrientes = json.loads(leitura.valor) if isinstance(leitura.valor, str) else leitura.valor
                        if isinstance(nutrientes, dict):
                            if 'P' in nutrientes:
                                valores_p.append(float(nutrientes['P']))
                            if 'K' in nutrientes:
                                valores_k.append(float(nutrientes['K']))
                    except (json.JSONDecodeError, ValueError):
                        # Se não for JSON, tentar interpretar como valor único
                        if leitura.unidade == 'P_ppm':
                            valores_p.append(leitura.valor)
                        elif leitura.unidade == 'K_ppm':
                            valores_k.append(leitura.valor)
                
                # Calcular médias (se houver valores)
                media_p = sum(valores_p) / len(valores_p) if valores_p else 0
                media_k = sum(valores_k) / len(valores_k) if valores_k else 0
                
                # Obter níveis ideais da cultura plantada
                cultura_nome = campo.get('campo', {}).get('cultura_plantada', '')
                cultura = mongo_db.obter_cultura_por_nome(cultura_nome) if cultura_nome else None
                
                if cultura:
                    # Obter valores de referência de P e K da cultura
                    p_ideal = cultura.get('fertilizantes_insumos', {}).get('adubacao_NPK_por_hectare_kg', {}).get('P2O5', 0)
                    k_ideal = cultura.get('fertilizantes_insumos', {}).get('adubacao_NPK_por_hectare_kg', {}).get('K2O', 0)
                    
                    # Converter de ppm para kg/ha (aproximação simplificada)
                    p_atual_kg_ha = media_p * 2.29 / 10  # Conversão aproximada de ppm P para kg/ha P2O5
                    k_atual_kg_ha = media_k * 1.2 / 10   # Conversão aproximada de ppm K para kg/ha K2O
                    
                    area_hectare = campo.get('campo', {}).get('area_total_hectare', 0)
                    
                    # Verificar deficiência de P
                    if p_atual_kg_ha < p_ideal * 0.7:  # 70% do ideal
                        p_deficit = (p_ideal * 0.7 - p_atual_kg_ha) * area_hectare
                        
                        recomendacao_id = sql_db.adicionar_recomendacao(
                            campo_id,
                            "fertilizante P2O5",
                            p_deficit,
                            "kg",
                            f"Nível de P: {media_p} ppm - Abaixo do ideal"
                        )
                        
                        resultado["recomendacoes"].append({
                            "id": recomendacao_id,
                            "tipo": "fertilização com fósforo",
                            "quantidade": p_deficit,
                            "unidade": "kg",
                            "motivo": f"Nível de fósforo está abaixo do ideal"
                        })
                    
                    # Verificar deficiência de K
                    if k_atual_kg_ha < k_ideal * 0.7:  # 70% do ideal
                        k_deficit = (k_ideal * 0.7 - k_atual_kg_ha) * area_hectare
                        
                        recomendacao_id = sql_db.adicionar_recomendacao(
                            campo_id,
                            "fertilizante K2O",
                            k_deficit,
                            "kg",
                            f"Nível de K: {media_k} ppm - Abaixo do ideal"
                        )
                        
                        resultado["recomendacoes"].append({
                            "id": recomendacao_id,
                            "tipo": "fertilização com potássio",
                            "quantidade": k_deficit,
                            "unidade": "kg",
                            "motivo": f"Nível de potássio está abaixo do ideal"
                        })
    
    return jsonify(resultado)

@sensor_bp.route('/api/aplicar-recomendacao/<int:recomendacao_id>', methods=['POST'])
def aplicar_recomendacao(recomendacao_id):
    """Registra a aplicação de uma recomendação"""
    sql_db = get_sql_db()
    
    # Obter a recomendação
    session = sql_db.get_session()
    recomendacao = None
    try:
        from app.models.sensor_models import RecomendacaoAutomatica
        recomendacao = session.query(RecomendacaoAutomatica).filter_by(id=recomendacao_id).first()
    finally:
        session.close()
    
    if not recomendacao:
        return jsonify({"erro": "Recomendação não encontrada"}), 404
    
    # Registrar a aplicação
    metodo_aplicacao = request.json.get('metodo_aplicacao', '') if request.is_json else request.form.get('metodo_aplicacao', '')
    
    try:
        # Registrar a aplicação do recurso
        aplicacao_id = sql_db.adicionar_aplicacao_recurso(
            recomendacao.campo_id,
            recomendacao.tipo_recurso,
            recomendacao.quantidade_recomendada,
            recomendacao.unidade,
            metodo_aplicacao
        )
        
        # Marcar a recomendação como aplicada
        sql_db.marcar_recomendacao_aplicada(recomendacao_id)
        
        return jsonify({
            "mensagem": "Recomendação aplicada com sucesso",
            "aplicacao_id": aplicacao_id
        })
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@sensor_bp.route('/relatorios')
def relatorios():
    """Página de relatórios de sensores"""
    return render_template('sensores/relatorios.html')

@sensor_bp.route('/api/relatorio/sensor/<int:sensor_id>', methods=['GET'])
def relatorio_sensor(sensor_id):
    """Gera um relatório para um sensor específico"""
    sql_db = get_sql_db()
    
    # Obter sensor
    sensor = sql_db.obter_sensor(sensor_id)
    if not sensor:
        return jsonify({"erro": "Sensor não encontrado"}), 404
    
    # Parâmetros de período
    dias = request.args.get('dias', '30')
    try:
        dias = int(dias)
    except ValueError:
        dias = 30
    
    data_fim = datetime.now()
    data_inicio = data_fim - timedelta(days=dias)
    
    # Obter leituras do período
    leituras = sql_db.obter_leituras_por_sensor(sensor_id, data_inicio, data_fim)
    
    # Calcular estatísticas
    estatisticas = sql_db.calcular_estatisticas_leituras(sensor_id, data_inicio, data_fim)
    
    # Gerar histórico (se ainda não existir)
    sql_db.gerar_historico(sensor_id, data_inicio, data_fim)
    
    # Formatar dados para o relatório
    dados_leituras = []
    for leitura in leituras:
        dados_leituras.append({
            "id": leitura.id,
            "data_hora": leitura.data_hora.isoformat(),
            "valor": leitura.valor,
            "unidade": leitura.unidade
        })
    
    return jsonify({
        "sensor": {
            "id": sensor.id,
            "tipo": sensor.tipo,
            "modelo": sensor.modelo
        },
        "periodo": {
            "inicio": data_inicio.isoformat(),
            "fim": data_fim.isoformat(),
            "dias": dias
        },
        "estatisticas": estatisticas,
        "leituras": dados_leituras
    })

@sensor_bp.route('/api/relatorio/campo/<campo_id>', methods=['GET'])
def relatorio_campo(campo_id):
    """Gera um relatório para um campo específico"""
    sql_db = get_sql_db()
    mongo_db = get_mongo_db()
    
    # Obter campo
    campo = mongo_db.obter_campo_por_id(campo_id)
    if not campo:
        return jsonify({"erro": "Campo não encontrado"}), 404
    
    # Parâmetros de período
    dias = request.args.get('dias', '30')
    try:
        dias = int(dias)
    except ValueError:
        dias = 30
    
    data_fim = datetime.now()
    data_inicio = data_fim - timedelta(days=dias)
    
    # Obter sensores do campo
    sensores = sql_db.obter_sensores_por_campo(campo_id)
    
    # Obter aplicações de recursos no período
    aplicacoes = sql_db.obter_aplicacoes_recurso(campo_id, inicio=data_inicio, fim=data_fim)
    
    # Formatar dados para o relatório
    dados_sensores = []
    for sensor in sensores:
        estatisticas = sql_db.calcular_estatisticas_leituras(sensor.id, data_inicio, data_fim)
        dados_sensores.append({
            "id": sensor.id,
            "tipo": sensor.tipo,
            "estatisticas": estatisticas
        })
    
    dados_aplicacoes = []
    for aplicacao in aplicacoes:
        dados_aplicacoes.append({
            "id": aplicacao.id,
            "data_hora": aplicacao.data_hora.isoformat(),
            "tipo_recurso": aplicacao.tipo_recurso,
            "quantidade": aplicacao.quantidade,
            "unidade": aplicacao.unidade
        })
    
    return jsonify({
        "campo": {
            "id": campo_id,
            "nome_produtor": campo.get('nome_produtor', ''),
            "cultura_plantada": campo.get('campo', {}).get('cultura_plantada', ''),
            "area_hectare": campo.get('campo', {}).get('area_total_hectare', 0)
        },
        "periodo": {
            "inicio": data_inicio.isoformat(),
            "fim": data_fim.isoformat(),
            "dias": dias
        },
        "sensores": dados_sensores,
        "aplicacoes": dados_aplicacoes
    })

# API para simulação de sensores (para testes/desenvolvimento)
@sensor_bp.route('/api/simular-leituras', methods=['POST'])
def simular_leituras():
    """Endpoint para simular leituras de sensores (para desenvolvimento)"""
    if not current_app.config['DEBUG']:
        return jsonify({"erro": "Simulação disponível apenas em ambiente de desenvolvimento"}), 403
    
    sql_db = get_sql_db()
    
    # Parâmetros
    campo_id = request.json.get('campo_id')
    if not campo_id:
        return jsonify({"erro": "Campo ID é obrigatório"}), 400
    
    # Verificar se o campo existe
    mongo_db = get_mongo_db()
    campo = mongo_db.obter_campo_por_id(campo_id)
    if not campo:
        return jsonify({"erro": "Campo não encontrado"}), 404
    
    # Verificar se já existem sensores neste campo
    sensores = sql_db.obter_sensores_por_campo(campo_id)
    
    # Se não existirem sensores, criar alguns
    if not sensores:
        # Criar 3 sensores, um de cada tipo
        sensor_ids = []
        for tipo in ['S1', 'S2', 'S3']:
            sensor_id = sql_db.adicionar_sensor(tipo, f"Sensor {tipo} Simulado")
            sql_db.adicionar_posicao_sensor(sensor_id, campo_id)
            sensor_ids.append(sensor_id)
        
        # Obter os sensores novamente
        sensores = sql_db.obter_sensores_por_campo(campo_id)
    
    # Simular leituras para cada sensor
    import random
    resultados = []
    
    for sensor in sensores:
        if sensor.tipo == 'S1':  # Sensor de umidade
            # Simular umidade do solo (15% a 70%)
            valor = random.uniform(15.0, 70.0)
            unidade = '%'
            
        elif sensor.tipo == 'S2':  # Sensor de pH
            # Simular pH do solo (4.5 a 8.0)
            valor = random.uniform(4.5, 8.0)
            unidade = 'pH'
            
        elif sensor.tipo == 'S3':  # Sensor de nutrientes
            # Simular valores de P e K
            valor_p = random.uniform(5.0, 50.0)  # ppm de P
            valor_k = random.uniform(10.0, 100.0)  # ppm de K
            valor = f'{{"P": {valor_p:.1f}, "K": {valor_k:.1f}}}'
            unidade = 'ppm'
        
        # Registrar a leitura
        leitura_id = sql_db.adicionar_leitura(sensor.id, valor, unidade)
        
        resultados.append({
            "sensor_id": sensor.id,
            "tipo": sensor.tipo,
            "leitura_id": leitura_id,
            "valor": valor,
            "unidade": unidade
        })
    
    # Gerar uma recomendação aleatória
    if random.random() < 0.3:  # 30% de chance de gerar uma recomendação
        tipo_recurso = random.choice(['água', 'fertilizante N', 'fertilizante P2O5', 'fertilizante K2O', 'calcário'])
        quantidade = random.uniform(10.0, 100.0)
        unidade = 'L' if tipo_recurso == 'água' else 'kg'
        
        recomendacao_id = sql_db.adicionar_recomendacao(
            campo_id,
            tipo_recurso,
            quantidade,
            unidade,
            "Recomendação gerada por simulação"
        )
        
        resultados.append({
            "recomendacao_id": recomendacao_id,
            "tipo_recurso": tipo_recurso,
            "quantidade": quantidade,
            "unidade": unidade
        })
    
    return jsonify({
        "mensagem": "Simulação concluída com sucesso",
        "resultados": resultados
    })
    
    # Adicione essas rotas ao arquivo sensor_routes.py

@sensor_bp.route('/api/sensores', methods=['GET'])
def listar_sensores_api():
    """API para listar todos os sensores ativos"""
    sql_db = get_sql_db()
    
    try:
        from app.models.sensor_models import Sensor
        session = sql_db.get_session()
        sensores = session.query(Sensor).filter_by(ativo=True).all()
        
        sensores_json = []
        for sensor in sensores:
            sensores_json.append({
                'id': sensor.id,
                'tipo': sensor.tipo,
                'modelo': sensor.modelo
            })
        
        return jsonify(sensores_json)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        session.close()