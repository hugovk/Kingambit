import io
import os
import tempfile
import subprocess
import json
from pathlib import Path
from typing import Dict, Any, List
from PIL import Image, ExifTags

TIPOS_IMAGEM = frozenset({
    ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp",
})

FORMATOS_IMAGEM_SUPORTADOS = frozenset({
    "JPEG", "PNG", "WEBP", "TIFF", "BMP",
})

TIPOS_VIDEO = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".m4v",
})

CAMPOS_BINARIOS = frozenset({
    "item 0", "item 1", "item 2", "item 3",
    "item 1 sig tst 2 tst tokens val",
    "item 1r vals ocsp vals",
    "item 1 pad", "item 1 pad 2",
    "created assertions hash",
    "hash", "pad",
})

CAMPOS_IGNORADOS = frozenset({
    "sourcefile", "exiftoolversion", "directory", "gpslatitude",
    "gpslongitude", "gpsaltitude", "gpsposition", "serialnumber",
    "bodyserialnumber", "lensserialnumber", "internalserialnumber",
})

CAMPOS_IA = {
    "software": [
        "stable diffusion", "midjourney", "dall-e", "dalle",
        "novelai", "comfyui", "automatic1111", "invoke",
        "diffusers", "dreamstudio", "leonardo", "playground",
        "adobe firefly", "firefly", "bing image creator",
        "copilot", "chatgpt", "gpt", "gemini", "ideogram",
    ],
    "chaves": [
        "software", "generator", "creator", "creatortool",
        "historysoftwareagent", "comment", "usercomment",
        "description", "imagedescription", "xmptoolkit",
        "source", "aimodel", "prompt",
        "negativeprompt", "sampler", "cfgscale", "steps",
        "seed", "denoisingstrength", "clipskip",
        "aigeneratedcontent", "aiassisted", "parameters",
    ],
}

CAMPOS_CAMERA = [
    "make", "model", "lensmodel", "lensmake", "lensinfo",
    "focallength", "focallengthin35mmformat", "focallengthin35mmfilm",
    "fnumber", "aperture", "aperturevalue",
    "exposuretime", "shutterspeedvalue", "shutterspeed",
    "iso", "isospeedratings", "photographicsensitivity",
    "flash", "flashfired", "flashmode",
    "whitebalance", "meteringmode", "exposuremode",
    "exposureprogram", "exposurecompensation",
    "scenecapturetype", "digitalzoomratio",
    "gaincontrol", "contrast", "saturation", "sharpness",
    "subjectdistance", "subjectdistancerange",
    "serialnumber", "bodyserialnumber", "lensserialnumber",
    "internalserialnumber",
]

CAMPOS_ARQUIVO = [
    "filename", "directory", "filesize", "filemodifydate",
    "fileaccessdate", "filecreatedate", "filetype",
    "filetypeextension", "mimetype", "imagewidth",
    "imageheight", "imagesize", "megapixels",
    "bitdepth", "colorspace", "colortype", "format",
    "compression", "quality", "encoding",
    "xresolution", "yresolution", "resolutionunit",
    "datetimeoriginal", "createdate", "modifydate",
    "offsettime", "offsettimeoriginal",
    "gpslatitude", "gpslongitude", "gpsaltitude",
    "gpsposition", "statusmetadados",
]

def detectar_tipo(nome: str) -> str:
    ext = Path(nome).suffix.lower()
    if ext in TIPOS_IMAGEM:
        return "imagem"
    if ext in TIPOS_VIDEO:
        return "video"
    raise ValueError("Tipo nao suportado")

def normalizar_metadados(dados: Dict[str, Any]) -> Dict[str, Any]:
    resultado = {}
    for chave, valor in dados.items():
        chave_limpa = chave.split(":")[-1]
        if chave_limpa.lower() in CAMPOS_IGNORADOS:
            continue
        if chave_limpa.lower() in CAMPOS_BINARIOS:
            continue
        if isinstance(valor, str) and "(Binary data" in valor:
            continue
        resultado[chave_limpa] = valor
    return resultado

def extrair_metadados_pillow(conteudo: bytes) -> Dict[str, Any]:
    dados = {}
    try:
        with Image.open(io.BytesIO(conteudo)) as img:
            dados["ImageWidth"] = img.width
            dados["ImageHeight"] = img.height
            dados["ColorType"] = img.mode
            dados["Format"] = img.format or "Desconhecido"
            
            if hasattr(img, "info") and isinstance(img.info, dict):
                for k, v in img.info.items():
                    if isinstance(v, (str, int, float, bool)):
                        dados[str(k)] = v
                    elif isinstance(v, bytes):
                        try:
                            dados[str(k)] = v.decode("utf-8", errors="ignore")
                        except Exception:
                            pass

            exif = img.getexif()
            if exif:
                for tag_id, val in exif.items():
                    tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                    if isinstance(val, bytes):
                        try:
                            val = val.decode("utf-8", errors="ignore")
                        except Exception:
                            continue
                    dados[tag_name] = str(val) if not isinstance(val, (int, float, str)) else val

                for ifd_id in (ExifTags.IFD.Exif, ExifTags.IFD.GPSInfo, ExifTags.IFD.MakerNote):
                    try:
                        ifd = exif.get_ifd(ifd_id)
                        for tag_id, val in ifd.items():
                            tag_name = ExifTags.TAGS.get(tag_id, ExifTags.GPSTAGS.get(tag_id, str(tag_id)))
                            if isinstance(val, bytes):
                                try:
                                    val = val.decode("utf-8", errors="ignore")
                                except Exception:
                                    continue
                            dados[tag_name] = str(val) if not isinstance(val, (int, float, str)) else val
                    except Exception:
                        pass
    except Exception:
        pass
    return normalizar_metadados(dados)

def extrair_metadados(conteudo: bytes, nome_arquivo: str) -> Dict[str, Any]:
    tipo = detectar_tipo(nome_arquivo)
    meta = {}
    
    sufixo = Path(nome_arquivo).suffix
    caminho_tmp = None
    status_exiftool = "indisponivel"
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=sufixo) as tmp:
            tmp.write(conteudo)
            caminho_tmp = tmp.name

        res = subprocess.run(
            ["exiftool", "-j", caminho_tmp],
            capture_output=True,
            text=True,
            timeout=5
        )
        if res.returncode == 0:
            dados_brutos = json.loads(res.stdout)
            if dados_brutos:
                meta = normalizar_metadados(dados_brutos[0])
            status_exiftool = "ok"
        else:
            status_exiftool = "falhou"
    except Exception as exc:
        status_exiftool = "falhou" if not isinstance(exc, FileNotFoundError) else "indisponivel"
    finally:
        if caminho_tmp:
            try:
                os.unlink(caminho_tmp)
            except OSError:
                pass

    if tipo == "imagem":
        meta_pillow = extrair_metadados_pillow(conteudo)
        for k, v in meta_pillow.items():
            if k not in meta:
                meta[k] = v

    meta["_nome_arquivo"] = nome_arquivo
    meta["_tipo_arquivo"] = tipo
    meta["_tamanho_kb"] = round(len(conteudo) / 1024, 2)
    meta["_exiftool_status"] = status_exiftool
    return meta

def categorizar_metadados(meta: Dict[str, Any]) -> Dict[str, Any]:
    ia = {}
    camera = {}
    arquivo = {}
    outros = {}
    indicios_ia: List[Dict[str, str]] = []

    for chave, valor in meta.items():
        if chave.startswith("_"):
            arquivo[chave] = valor
            continue

        chave_lower = chave.lower().replace(" ", "").replace("_", "")
        encontrado = False

        for campo_ia in CAMPOS_IA["chaves"]:
            if campo_ia in chave_lower:
                ia[chave] = valor
                encontrado = True
                if isinstance(valor, str):
                    valor_lower = valor.lower()
                    for termo in CAMPOS_IA["software"]:
                        if termo in valor_lower:
                            indicios_ia.append({
                                "campo": chave,
                                "valor": valor,
                                "motivo": f"Contem referencia a ferramenta de IA: {termo}",
                            })
                            break
                    palavras_suspeitas = [
                        "generated", "artificial", "synthetic", "neural",
                        "diffusion", "gan",
                    ]
                    for palavra in palavras_suspeitas:
                        if palavra in valor_lower and (palavra != "generated" or "generated by" in valor_lower):
                            indicios_ia.append({
                                "campo": chave,
                                "valor": valor,
                                "motivo": f"Contem termo associado a geracao artificial: {palavra}",
                            })
                            break
                break

        if encontrado:
            continue

        for campo_cam in CAMPOS_CAMERA:
            if campo_cam in chave_lower:
                camera[chave] = valor
                encontrado = True
                break

        if encontrado:
            continue

        for campo_arq in CAMPOS_ARQUIVO:
            if campo_arq in chave_lower:
                arquivo[chave] = valor
                encontrado = True
                break

        if encontrado:
            continue

        outros[chave] = valor

    if not ia and not camera.get("Make") and not camera.get("Model"):
        arquivo["StatusMetadados"] = "Metadados de camera nao disponiveis; isso nao determina autenticidade"

    return {
        "ia": ia,
        "indicios_ia": indicios_ia,
        "camera": camera,
        "arquivo": arquivo,
        "outros": outros,
    }
