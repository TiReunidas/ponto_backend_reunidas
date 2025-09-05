# cadastro.py
import cv2
import face_recognition
import numpy as np
import os

# --- CONFIGURAÇÕES ---
# Coloque aqui a matrícula da sua foto de referência
MATRICULA = "0601000343" 

REFERENCE_DIR = "fotos_referencia"
ENCODINGS_DIR = "encodings"
os.makedirs(ENCODINGS_DIR, exist_ok=True)

def cadastrar_funcionario(matricula):
    print(f"--- Iniciando cadastro para a matrícula: {matricula} ---")

    # Monta o caminho para a foto de referência
    foto_path = os.path.join(REFERENCE_DIR, f"{matricula}.jpg")

    if not os.path.exists(foto_path):
        print(f"ERRO: Foto de referência '{foto_path}' não encontrada.")
        return

    try:
        # Tenta carregar a imagem com OpenCV (Método Robusto)
        print(f"1. Carregando imagem: {foto_path}")
        imagem_bgr = cv2.imread(foto_path)
        if imagem_bgr is None:
            print("ERRO: OpenCV não conseguiu ler a imagem. O arquivo pode estar corrompido ou em um formato inválido.")
            return

        # Converte de BGR (padrão OpenCV) para RGB (padrão face_recognition)
        print("2. Convertendo imagem para RGB...")
        imagem_rgb = cv2.cvtColor(imagem_bgr, cv2.COLOR_BGR2RGB)

        # Tenta encontrar o rosto e gerar o encoding
        print("3. Procurando por rostos e gerando encoding...")
        encodings = face_recognition.face_encodings(imagem_rgb)

        if not encodings:
            print("ERRO: Nenhum rosto foi encontrado na imagem de referência. Tente uma foto mais nítida e de frente.")
            return

        # Pega o encoding do primeiro rosto encontrado
        encoding_rosto = encodings[0]
        print("4. Encoding gerado com sucesso!")

        # Salva o encoding em um arquivo .npy (formato do NumPy)
        encoding_path = os.path.join(ENCODINGS_DIR, f"{matricula}.npy")
        np.save(encoding_path, encoding_rosto)

        print(f"5. SUCESSO! Digital facial salva em: {encoding_path}")

    except Exception as e:
        print(f"\n!!!!!!!! OCORREU UM ERRO INESPERADO !!!!!!!!")
        print(f"Erro: {e}")

# --- Ponto de entrada do script ---
if __name__ == "__main__":
    cadastrar_funcionario(MATRICULA)