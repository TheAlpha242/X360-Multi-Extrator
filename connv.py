from PIL import Image, ImageDraw

def recortar_circulo_transparente(imagem_origem, png_saida="img/logo.png", ico_saida="img/logo.ico"):
    # Carrega a imagem original
    img = Image.open(imagem_origem).convert("RGBA")
    largura, altura = img.size

    # O círculo central está contido na menor dimensão
    tamanho = min(largura, altura)

    # Coordenadas do recorte centralizado
    esquerda = (largura - tamanho) // 2
    topo = (altura - tamanho) // 2
    direita = esquerda + tamanho
    fundo = topo + tamanho

    # Corta em um quadrado exato centrado no círculo
    img_quadrada = img.crop((esquerda, topo, direita, fundo))

    # Cria uma máscara alfa circular de alta precisão
    mascara = Image.new("L", (tamanho, tamanho), 0)
    draw = ImageDraw.Draw(mascara)
    draw.ellipse((0, 0, tamanho, tamanho), fill=255)

    # Aplica a máscara no canal alfa da imagem
    img_quadrada.putalpha(mascara)

    # 1. Salva em PNG com transparência real
    img_quadrada.save(png_saida, format="PNG")
    print(f"✅ PNG com canal alfa real salvo em: {png_saida}")

    # 2. Salva em formato .ICO com todas as camadas de resolução do Windows
    tamanhos_ico = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    img_quadrada.save(ico_saida, format="ICO", sizes=tamanhos_ico)
    print(f"✅ Arquivo .ICO multi-resolução salvo em: {ico_saida}")

if __name__ == "__main__":
    # Substitua pelo nome do arquivo original (a primeira imagem quadrada/retangular que você tem aí)
    recortar_circulo_transparente("Gemini_Generated_Image.jpeg")