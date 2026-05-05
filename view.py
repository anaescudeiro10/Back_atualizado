import datetime
import os
import threading
from flask_mail import Mail
import datetime
import random
import threading
import jwt
from flask import jsonify, request, make_response
from main import app, get_db_connection
from funcao import (verificar_senha, criptografar, checar_senha,
                    enviando_email, gerar_token, verificar_reuso_senha, gerar_codigo)

UPLOAD_FOLDER = os.path.join(app.config['UPLOAD_FOLDER'], "usuarios")
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


@app.route('/criar_usuario', methods=['POST'])
def criar_usuario():
    con = get_db_connection()
    cur = con.cursor()
    try:
        nome = request.form.get('nome')
        email = request.form.get('email')
        senha = request.form.get('senha')
        tipo = request.form.get('tipo', 'cliente').lower()
        foto = request.files.get('foto')

        if not nome or not email or not senha:
            return jsonify({'erro': 'Nome, Email e Senha são obrigatórios.'}), 400

        erro_senha = verificar_senha(senha)
        if erro_senha: return jsonify({'erro': erro_senha}), 400

        cur.execute("SELECT ID_USUARIO FROM USUARIOS WHERE EMAIL = ?", (email,))
        if cur.fetchone(): return jsonify({'erro': 'E-mail já cadastrado.'}), 409

        senha_hash = criptografar(senha)
        codigo_confirmacao = gerar_codigo()

        cur.execute("""
            INSERT INTO USUARIOS (NOME, EMAIL, SENHA, TIPO, CONTA_CONFIRMADA, BLOQUEADO, TENTATIVAS_LOGIN)
            VALUES (?, ?, ?, ?, 0, 0, 0)
            RETURNING ID_USUARIO
        """, (nome, email, senha_hash, tipo))
        id_usuario = cur.fetchone()[0]

        if foto:
            foto.save(os.path.join(UPLOAD_FOLDER, f"perfil_{id_usuario}.jpg"))

        if tipo == 'cliente':
            cur.execute("INSERT INTO CLIENTES (ID_USUARIO, NOME) VALUES (?, ?)", (id_usuario, nome))
            cur.execute("INSERT INTO CONFIRMAR_CODIGO (ID_USUARIO, CODIGO, UTILIZADO) VALUES (?, ?, 0)",
                        (id_usuario, codigo_confirmacao))

        con.commit()

        assunto = "Confirme seu cadastro"
        corpo = f"Seu código de confirmação é: {codigo_confirmacao}"
        threading.Thread(target=enviando_email, args=(email, assunto, corpo)).start()

        return jsonify({
            "mensagem": "Usuário criado! Verifique seu e-mail.",
            "id_usuario": id_usuario
        }), 201

    except Exception as e:
        con.rollback()
        return jsonify({'erro': f"Erro no banco: {str(e)}"}), 500
    finally:
        con.close()


@app.route('/confirmar_codigo', methods=['POST'])
def confirmar_codigo():
    con = get_db_connection()
    cur = con.cursor()
    try:
        dados = request.get_json(silent=True) or request.form

        id_user = dados.get('id_usuario')
        cod = dados.get('codigo')

        cur.execute("EXECUTE PROCEDURE SP_CONFIRMAR_CADASTRO (?, ?)", (id_user, cod))
        con.commit()

        return jsonify({"mensagem": "Conta confirmada com sucesso!"}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 400
    finally:
        con.close()

@app.route('/login_usuario', methods=['POST'])
def login_usuario():
    con = get_db_connection()
    cur = con.cursor()
    dados = request.get_json(silent=True) or request.form
    email = dados.get('email')
    senha = dados.get('senha')

    try:
        cur.execute("""
            SELECT ID_USUARIO, SENHA, NOME, TIPO, CONTA_CONFIRMADA, BLOQUEADO, TENTATIVAS_LOGIN 
            FROM USUARIOS WHERE EMAIL = ?
        """, (email,))
        res = cur.fetchone()

        if not res:
            return jsonify({'erro': 'Usuário não encontrado'}), 404

        id_user, hash_db, nome, tipo, confirmado, bloqueado, tentativas = res

        if bloqueado == 1:
            return jsonify({'erro': 'Conta bloqueada por excesso de tentativas. Contate o administrador.'}), 403

        if confirmado == 0:
            return jsonify({'erro': 'E-mail não confirmado.'}), 403

        if checar_senha(senha, hash_db):
            cur.execute("UPDATE USUARIOS SET TENTATIVAS_LOGIN = 0 WHERE ID_USUARIO = ?", (id_user,))
            con.commit()

            token_payload = {
                'id': id_user,
                'tipo': tipo,
                'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=1)
            }
            token = jwt.encode(token_payload, app.config['SECRET_KEY'], algorithm="HS256")

            return jsonify({'mensagem': f'Bem-vindo {nome}!', 'token': token, 'tipo': tipo}), 200

        else:
            tentativas += 1

            if tentativas >= 3:
                cur.execute("UPDATE USUARIOS SET TENTATIVAS_LOGIN = ?, BLOQUEADO = 1 WHERE ID_USUARIO = ?",
                            (tentativas, id_user))
                con.commit()
                return jsonify({'erro': 'Senha incorreta. Conta bloqueada após 3 tentativas.'}), 403
            else:
                cur.execute("UPDATE USUARIOS SET TENTATIVAS_LOGIN = ? WHERE ID_USUARIO = ?",
                            (tentativas, id_user))
                con.commit()
                return jsonify({'erro': f'Senha incorreta. Tentativa {tentativas} de 3.'}), 401

    except Exception as e:
        con.rollback()
        return jsonify({'erro': f'Erro interno: {str(e)}'}), 500
    finally:
        con.close()


@app.route('/usuarios', methods=['GET'])
def listar_usuarios():
    con = get_db_connection()
    cur = con.cursor()
    try:
        cur.execute("SELECT ID_USUARIO, NOME, EMAIL, TIPO, BLOQUEADO FROM USUARIOS")
        usuarios = cur.fetchall()

        resultado = []
        for u in usuarios:
            resultado.append({
                'id': u[0],
                'nome': u[1],
                'email': u[2],
                'tipo': u[3],
                'bloqueado': "Sim" if u[4] == 1 else "Não"
            })

        return jsonify(resultado), 200
    except Exception as e:
        return jsonify({'erro': f"Erro ao listar: {str(e)}"}), 500
    finally:
        cur.close()
        con.close()


@app.route('/editar_usuario/<int:id_usuario>', methods=['PUT', 'POST'])
def editar_usuario(id_usuario):
    con = get_db_connection()
    cur = con.cursor()
    try:
        cur.execute("SELECT SENHA, NOME FROM USUARIOS WHERE ID_USUARIO = ?", (id_usuario,))
        res = cur.fetchone()
        if not res:
            return jsonify({'erro': 'Usuário não encontrado'}), 404

        hash_atual, nome_atual = res

        nome = request.form.get('nome')
        senha_nova = request.form.get('senha')
        foto = request.files.get('foto')

        if nome is not None and nome.strip() == "":
            return jsonify({'erro': 'O nome não pode ficar vazio.'}), 400

        nome_final = nome if nome else nome_atual

        senha_final = hash_atual

        if senha_nova and senha_nova.strip() != "":
            erro_senha = verificar_senha(senha_nova)
            if erro_senha:
                return jsonify({'erro': erro_senha}), 400

            if verificar_reuso_senha(id_usuario, senha_nova, cur):
                return jsonify({'erro': 'Esta senha já foi usada nas últimas 3 trocas.'}), 400

            cur.execute("INSERT INTO HISTORICO_SENHAS (ID_USUARIO, SENHA_ANTIGA) VALUES (?, ?)",
                        (id_usuario, hash_atual))

            senha_final = criptografar(senha_nova)

        cur.execute("UPDATE USUARIOS SET NOME = ?, SENHA = ? WHERE ID_USUARIO = ?",
                    (nome_final, senha_final, id_usuario))

        if foto:
            foto.save(os.path.join(UPLOAD_FOLDER, f"perfil_{id_usuario}.jpg"))

        con.commit()
        return jsonify({'mensagem': 'Perfil atualizado com sucesso!'}), 200

    except Exception as e:
        con.rollback()
        return jsonify({'erro': f"Erro ao editar: {str(e)}"}), 500
    finally:
        cur.close()
        con.close()


@app.route('/logout', methods=['POST'])
def logout():
    resp = make_response(jsonify({'mensagem': 'Logout realizado'}), 200)
    resp.delete_cookie('access_token')
    return resp



@app.route('/excluir_usuario/<int:id_usuario>', methods=['DELETE'])
def excluir_usuario(id_usuario):
    con = get_db_connection()
    cur = con.cursor()
    try:
        cur.execute("DELETE FROM CLIENTES WHERE ID_USUARIO = ?", (id_usuario,))
        cur.execute("DELETE FROM CONFIRMAR_CODIGO WHERE ID_USUARIO = ?", (id_usuario,))

        cur.execute("DELETE FROM USUARIOS WHERE ID_USUARIO = ?", (id_usuario,))

        if cur.rowcount == 0:
            return jsonify({'erro': 'Usuário não encontrado.'}), 404

        con.commit()
        return jsonify({'mensagem': 'Usuário e dados relacionados removidos com sucesso.'}), 200
    except Exception as e:
        con.rollback()
        return jsonify({'erro': f"Erro ao excluir: {str(e)}"}), 500
    finally:
        con.close()



@app.route('/admin/desbloquear/<int:id_usuario>', methods=['POST'])
def desbloquear_usuario(id_usuario):
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return jsonify({'erro': 'Acesso negado: Token não fornecido.'}), 401

    try:
        token = auth_header.split(" ")[1]
        dados_token = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])

        if dados_token.get('tipo') != 'admin':
            return jsonify({'erro': 'Proibido: Apenas administradores podem realizar esta ação.'}), 403

    except jwt.ExpiredSignatureError:
        return jsonify({'erro': 'Sua sessão expirou. Faça login novamente.'}), 401
    except Exception:
        return jsonify({'erro': 'Token inválido ou corrompido.'}), 401

    con = get_db_connection()
    cur = con.cursor()
    try:
        cur.execute("SELECT NOME, BLOQUEADO FROM USUARIOS WHERE ID_USUARIO = ?", (id_usuario,))
        usuario = cur.fetchone()

        if not usuario:
            return jsonify({'erro': f'O usuário com ID {id_usuario} não existe em nossa base.'}), 404

        if usuario[1] == 0:
            return jsonify({'mensagem': f'O usuário {usuario[0]} já está desbloqueado.'}), 200

        cur.execute("""
            UPDATE USUARIOS 
            SET BLOQUEADO = 0, TENTATIVAS_LOGIN = 0 
            WHERE ID_USUARIO = ?
        """, (id_usuario,))

        con.commit()
        return jsonify({'mensagem': f'Sucesso! O usuário {usuario[0]} foi liberado.'}), 200

    except Exception as e:
        con.rollback()
        return jsonify({'erro': 'Erro interno ao acessar o banco de dados.'}), 500
    finally:
        cur.close()
        con.close()

@app.route('/admin/buscar_nome', methods=['GET'])
def buscar_usuario_nome():
    nome_busca = request.args.get('nome', '')

    con = get_db_connection()
    cur = con.cursor()
    try:
        cur.execute("""
            SELECT ID_USUARIO, NOME, EMAIL FROM USUARIOS 
            WHERE UPPER(NOME) LIKE UPPER(?)
        """, (f'%{nome_busca}%',))

        usuarios = cur.fetchall()
        resultado = [{'id': u[0], 'nome': u[1], 'email': u[2]} for u in usuarios]
        return jsonify(resultado), 200
    except Exception as e:
        return jsonify({'erro': str(e)}), 500
    finally:
        cur.close()
        con.close()


@app.route('/solicitar_recuperacao', methods=['POST'])
def solicitar_recuperacao():
    con = get_db_connection()
    cur = con.cursor()
    try:
        email = request.form.get('email')

        if not email:
            return jsonify({'erro': 'O e-mail é obrigatório.'}), 400

        cur.execute("SELECT ID_USUARIO, NOME FROM USUARIOS WHERE EMAIL = ?", (email,))
        usuario = cur.fetchone()

        if not usuario:
            return jsonify({'erro': 'Usuário não encontrado.'}), 404

        id_usuario = usuario[0]
        nome_usuario = usuario[1]
        codigo = str(random.randint(100000, 999999))
        expiracao = datetime.datetime.now() + datetime.timedelta(minutes=10)

        cur.execute("""
            INSERT INTO RECUPERAR_SENHA (ID_USUARIO, CODIGO, EXPIRACAO, UTILIZADO)
            VALUES (?, ?, ?, 0)
        """, (id_usuario, codigo, expiracao))

        con.commit()

        assunto = "Recuperação de Senha"
        corpo = f"Olá {nome_usuario}, seu código de recuperação de senha é: {codigo}"
        threading.Thread(target=enviando_email, args=(email, assunto, corpo)).start()

        return jsonify({"mensagem": "Código de recuperação enviado para o e-mail!"}), 200

    except Exception as e:
        con.rollback()
        return jsonify({'erro': f"Erro no banco: {str(e)}"}), 500
    finally:
        con.close()


@app.route('/redefinir_senha', methods=['POST'])
def redefinir_senha():
    con = get_db_connection()
    cur = con.cursor()
    try:
        email = request.form.get('email')
        codigo = request.form.get('codigo')
        nova_senha = request.form.get('nova_senha')

        if not email or not codigo or not nova_senha:
            return jsonify({'erro': 'E-mail, código e nova senha são obrigatórios.'}), 400

        cur.execute("SELECT ID_USUARIO FROM USUARIOS WHERE EMAIL = ?", (email,))
        user = cur.fetchone()
        if not user: return jsonify({'erro': 'Usuário não encontrado.'}), 404
        id_usuario = user[0]

        cur.execute("""
            SELECT CODIGO FROM RECUPERAR_SENHA 
            WHERE ID_USUARIO = ? AND CODIGO = ? AND UTILIZADO = 0 AND EXPIRACAO > ?
        """, (id_usuario, codigo, datetime.datetime.now()))

        if not cur.fetchone():
            return jsonify({'erro': 'Código inválido ou expirado.'}), 400

        erro_senha = verificar_senha(nova_senha)
        if erro_senha: return jsonify({'erro': erro_senha}), 400

        senha_hash = criptografar(nova_senha)

        cur.execute("""
            UPDATE USUARIOS 
            SET SENHA = ?, BLOQUEADO = 0, TENTATIVAS_LOGIN = 0 
            WHERE ID_USUARIO = ?
        """, (senha_hash, id_usuario))

        cur.execute("UPDATE RECUPERAR_SENHA SET UTILIZADO = 1 WHERE ID_USUARIO = ? AND CODIGO = ?",
                    (id_usuario, codigo))

        con.commit()
        return jsonify({"mensagem": "Senha alterada com sucesso! Você já pode logar."}), 200

    except Exception as e:
        con.rollback()
        return jsonify({'erro': f"Erro no banco: {str(e)}"}), 500
    finally:
        con.close()
