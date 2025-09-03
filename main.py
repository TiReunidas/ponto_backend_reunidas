# main.py (Versão final com DeepFace)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import shutil
import logging
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from deepface import DeepFace # <-- NOSSA NOVA BIBLIOTECA

# --- CONFIGURAÇÃO ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

REFERENCE_DIR = "fotos_referencia"
PUNCH_DIR = "fotos_batidas"
os.makedirs(REFERENCE_DIR, exist_ok=True)
os.makedirs(PUNCH_DIR, exist_ok=True)


@app.get("/")
def read_root():
    return FileResponse('static/index.html')

@app.get("/employees")
def get_employees():
    """
    Lista todos os funcionários cadastrados com base nas fotos de referência.
    """
    logger.info("Requisição para listar funcionários recebida.")
    try:
        # Pega todos os arquivos na pasta de referência que terminam com .jpg
        files = [f for f in os.listdir(REFERENCE_DIR) if f.endswith('.jpg')]

        # Extrai apenas a matrícula (o nome do arquivo sem a extensão .jpg)
        employee_ids = [os.path.splitext(f)[0] for f in files]

        logger.info(f"Encontrados {len(employee_ids)} funcionários.")
        return {"employees": employee_ids}

    except Exception as e:
        logger.error(f"Erro ao listar funcionários: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar lista de funcionários.")


@app.post("/punch")
async def create_punch(
    employee_id: str = Form(...),
    photo: UploadFile = File(...)
):
    logger.info(f"--- INICIANDO PROCESSO PARA MATRÍCULA: {employee_id} ---")

    # Salva a foto da batida para fins de auditoria
    punch_photo_path = os.path.join(PUNCH_DIR, f"{employee_id}-{photo.filename}")
    with open(punch_photo_path, "wb") as buffer:
        shutil.copyfileobj(photo.file, buffer)
    logger.info(f"Foto da batida salva em: {punch_photo_path}")

    # Encontra o caminho da foto de referência
    reference_photo_path = os.path.join(REFERENCE_DIR, f"{employee_id}.jpg")
    if not os.path.exists(reference_photo_path):
        logger.error(f"Foto de referência não encontrada para a matrícula: {employee_id}")
        raise HTTPException(status_code=404, detail="Funcionário não cadastrado.")

    try:
        # --- A MÁGICA DA DEEPFACE ---
        logger.info(f"Verificando foto '{punch_photo_path}' contra '{reference_photo_path}'...")
        
        # A função verify faz todo o trabalho pesado para nós
        result = DeepFace.verify(
            img1_path = reference_photo_path,
            img2_path = punch_photo_path,
            model_name = "VGG-Face", # Modelo confiável
            enforce_detection = True # Garante que um rosto seja detectado em ambas as fotos
        )

        is_match = result["verified"]
        logger.info(f"Resultado da verificação para {employee_id}: {'Match' if is_match else 'No Match'}")

        # Retorna o resultado completo para o app
        return {
            "status": "success",
            "message": "Ponto processado com sucesso.",
            "verified": is_match,
            "distance": result["distance"] # Distância facial, útil para depuração
        }

    except ValueError as e:
        # Este erro é comum se a DeepFace não encontrar um rosto
        logger.warning(f"Não foi possível encontrar um rosto em uma das imagens: {e}")
        return {
            "status": "error",
            "message": "Não foi possível detectar um rosto na foto enviada.",
            "verified": False
        }
    except Exception as e:
        logger.error(f"Ocorreu um erro inesperado durante a verificação: {e}")
        raise HTTPException(status_code=500, detail="Erro interno no processamento da imagem.")