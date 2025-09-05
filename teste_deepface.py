# teste_deepface.py
from deepface import DeepFace
import cv2 # DeepFace usa OpenCV por baixo, então é bom ter

print("--- Testando a biblioteca DeepFace ---")

# Caminho para as duas imagens que vamos comparar
foto_referencia_path = r"fotos_referencia\0601000343.jpg"
foto_batida_path = r"fotos_batidas\teste.jpg" # Use aqui o nome da foto que você salvou para o teste

try:
    # Esta é a função principal da DeepFace.
    # Ela faz tudo: encontra o rosto, gera a "digital" e compara.
    # model_name='VGG-Face' é um dos modelos mais populares e confiáveis.
    resultado = DeepFace.verify(
        img1_path = foto_referencia_path,
        img2_path = foto_batida_path,
        model_name = 'VGG-Face'
    )

    print("\n--- Análise Concluída ---")
    print(f"As fotos são da mesma pessoa? {'Sim' if resultado['verified'] else 'Não'}")
    print("\nDetalhes do resultado:")
    print(resultado)

except Exception as e:
    print(f"\n!!!!!!!! OCORREU UM ERRO !!!!!!!!")
    print(f"Erro: {e}")