import os
class Config:
    DB_HOST = "localhost"
    DB_PATH = r"D:\BANCO (4)\BANCO.FDB"
    DB_USER = "SYSDBA"
    DB_PASSWORD = "sysdba"
    DB_CHARSET = "UTF8"

    SECRET_KEY = "chave_secreta"

    UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")

    CODIGO_EXPIRACAO_SEG = 600
    LIMITE_HISTORICO_SENHA = 3

if not os.path.exists(Config.UPLOAD_FOLDER):
    os.makedirs(Config.UPLOAD_FOLDER)