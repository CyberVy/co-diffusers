from diffusers import DiffusionPipeline,StableDiffusionPipeline,StableDiffusionXLPipeline,StableDiffusion3Pipeline
from diffusers import AutoencoderKL
from .download import download_file
from .const import hf_token
import requests
import torch
import os


def get_pipeline(model, model_version="", file_format="safetensors", download_kwargs=None, **kwargs):
    """

    :param model: hugging face repo id or unet file URI
    :param model_version: base model version, make sure this parameter is "xl" if the model is based on XL
    :param file_format: only for model while it is unet file, when not able to get the file format,this parameter will be the file format.
    :param download_kwargs:
    :param kwargs: for .from_pretrained
    :return:
    """
    use_internet = True
    model_version = model_version.lower()
    if download_kwargs is None:
        download_kwargs = {}
    if kwargs.get("token") is None:
        kwargs.update(token=hf_token)
    if kwargs.get("torch_dtype") is None:
        kwargs.update({"torch_dtype": torch.float16})
    if model.startswith(".") or model.startswith("/") or model.startswith("~"):
        use_internet = False

    if use_internet:
        # from Hugging face
        if not (model.startswith("http://") or model.startswith("https://")):
            text = requests.get(f"https://huggingface.co/{model}/tree/main/vae?not-for-all-audiences=true").text
            is_fp32 = "diffusion_pytorch_model.safetensors" in text
            is_fp16 = "diffusion_pytorch_model.fp16.safetensors" in text
            if is_fp16:
                kwargs.update({"variant": "fp16"})
                print("model.fp16.safetensors is selected.")
            elif is_fp32:
                print("model.safetensors is selected.")
            else:
                raise Exception("Model is not supported.")
            return DiffusionPipeline.from_pretrained(model, **kwargs)
        # from single file
        else:
            file_path = download_file(model,**download_kwargs)
            if model_version == "":
                print("Warning: Model version is not set, the pipeline may not work.")
                if "xl" in file_path.split("/")[-1].lower():
                    model_version = "xl"
            # bad file name from the url, 'filename.tensor/bin/ckpt' is wanted, but get 'filename'
            if not (file_path.endswith(".safetensors") or file_path.endswith(".bin") or file_path.endswith(".ckpt")):
                print(f"Warning: Can't get the format of the downloaded file, guess it is .{file_format}")
                os.rename(file_path,f"{file_path}.{file_format}")
                file_path = f"{file_path}.{file_format}"
            # load XL model with StableDiffusionPipeline seems ok, but never works
            # only StableDiffusionXLPipeline works
            if model_version == "xl":
                return StableDiffusionXLPipeline.from_single_file(file_path,**kwargs)
            elif model_version == "3":
                return StableDiffusion3Pipeline.from_single_file(file_path, **kwargs)
            else:
                return StableDiffusionPipeline.from_single_file(file_path, **kwargs)
    else:
        # from local single file
        if model.endswith(".safetensors") or model.endswith(".bin") or model.endswith(".ckpt"):
            if model_version == "":
                print("Warning: model version is not set, the pipeline may not work.")
                if "xl" in model.split("/")[-1].lower():
                    model_version = "xl"
            # the same reason above
            if model_version == "xl":
                return StableDiffusionXLPipeline.from_single_file(model,**kwargs)
            elif model_version == "3":
                return StableDiffusion3Pipeline.from_single_file(model,**kwargs)
            else:
                return StableDiffusionPipeline.from_single_file(model,**kwargs)
        # from standard model directory
        else:
            return DiffusionPipeline.from_pretrained(model, **kwargs)

def get_vae(vae_uri,download_kwargs=None,**kwargs):

    use_internet = True
    if download_kwargs is None:
        download_kwargs = {}

    if kwargs.get("torch_dtype") is None:
        kwargs.update({"torch_dtype": torch.float16})

    if vae_uri.startswith(".") or vae_uri.startswith("/") or vae_uri.startswith("~"):
        use_internet = False

    if use_internet:
        file_path = download_file(vae_uri,**download_kwargs)
        return AutoencoderKL.from_single_file(file_path,**kwargs)
    else:
        return AutoencoderKL.from_single_file(vae_uri,**kwargs)

def get_clip_from_pipeline(pipeline):

    tokenizers = []
    text_encoders = []
    tokenizer_names = ["tokenizer", "tokenizer_2", "tokenizer_3"]
    text_encoder_names = ["text_encoder", "text_encoder_2", "text_encoder_3"]
    for i, item in enumerate(tokenizer_names):
        if hasattr(pipeline, item):
            tokenizers.append(getattr(pipeline, item))
            text_encoders.append(getattr(pipeline, text_encoder_names[i]))
    return tokenizers,text_encoders
