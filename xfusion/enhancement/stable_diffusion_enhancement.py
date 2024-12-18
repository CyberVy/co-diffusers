# limited support to sd3 now

from .enhancement_utils import PipelineEnhancerBase,LoraEnhancerMixin,FromURLMixin,pipeline_map
from ..components.component_utils import get_tokenizers_and_text_encoders_from_pipeline
from ..components import load_stable_diffusion_pipeline
from ..ui.stable_diffusion_ui import load_stable_diffusion_ui
from ..ui.ui_utils import UIMixin
from ..utils import EasyInitSubclass
from ..message import TGBotMixin
from compel import Compel,ReturnedEmbeddingsType
import torch
from PIL import Image
import threading
from functools import lru_cache
from random import randint


def get_embeds_from_pipeline(pipeline,prompt,negative_prompt):
    """
    To overcome 77 tokens limit, and support high level syntax for prompts.
    limited support for sd1 sd2 sdxl

    :param pipeline:
    :param prompt:
    :param negative_prompt:
    :return:
    """
    tokenizers,text_encoders = get_tokenizers_and_text_encoders_from_pipeline(pipeline)
    tokenizers = [tokenizer for tokenizer in tokenizers if tokenizer]
    text_encoders = [text_encoder for text_encoder in text_encoders if text_encoder]
    for cls in pipeline_map["1.5"]:
        if isinstance(pipeline,cls):
            compel = Compel(tokenizers,text_encoders,truncate_long_prompts=False)
            conditioning = compel(prompt)
            negative_conditioning = compel(negative_prompt)
            [conditioning, negative_conditioning] = compel.pad_conditioning_tensors_to_same_length([conditioning, negative_conditioning])
            return {"prompt_embeds":conditioning,"negative_prompt_embeds":negative_conditioning}
    for cls in pipeline_map["xl"]:
        if isinstance(pipeline, cls):
            compel = Compel(tokenizers,text_encoders,returned_embeddings_type=ReturnedEmbeddingsType.PENULTIMATE_HIDDEN_STATES_NON_NORMALIZED,requires_pooled=[False,True],truncate_long_prompts=False)
            conditioning,pooled = compel(prompt)
            negative_conditioning, negative_pooled = compel(negative_prompt)
            [conditioning, negative_conditioning] = compel.pad_conditioning_tensors_to_same_length([conditioning, negative_conditioning])
            return {"prompt_embeds":conditioning,"negative_prompt_embeds":negative_conditioning,
                    "pooled_prompt_embeds":pooled,"negative_pooled_prompt_embeds":negative_pooled}
    # compel only supports sd1 sd2 sdxl now
    return {}

class SDCLIPEnhancerMixin:
    # __oins__ here is the pipeline instance to implement.
    __oins__ = None
    overrides = ["tokenizers","text_encoders","skip_clip_layer","get_embeds_from_pipeline","__call__"]

    def __init__(self):
        self.tokenizers, self.text_encoders = get_tokenizers_and_text_encoders_from_pipeline(self)

    def skip_clip_layer(self,n):
        text_encoders = [text_encoder for text_encoder in self.text_encoders if text_encoder]
        if isinstance(n,int) and  n >= 1:
            for text_encoder in text_encoders:
                if not hasattr(text_encoder.text_model.encoder,"backup_layers"):
                    text_encoder.text_model.encoder.backup_layers = text_encoder.text_model.encoder.layers
                text_encoder.text_model.encoder.layers = text_encoder.text_model.encoder.backup_layers[:-n]
        elif n is None or n == 0:
            for text_encoder in text_encoders:
                if hasattr(text_encoder.text_model.encoder,"backup_layers"):
                    text_encoder.text_model.encoder.layers = text_encoder.text_model.encoder.backup_layers
        else:
            raise ValueError("An integer >=0 is required.")

    def get_embeds_from_pipeline(self,prompt,negative_prompt,clip_skip=None):
        self.skip_clip_layer(clip_skip)
        r =  get_embeds_from_pipeline(self,prompt,negative_prompt)
        self.skip_clip_layer(0)
        return r

    def __call__(self,**kwargs):
        kwargs.update(self.get_embeds_from_pipeline(kwargs.get("prompt"),kwargs.get("negative_prompt"),kwargs.get("clip_skip")))
        if kwargs.get("prompt_embeds") is not None:
            kwargs.update(prompt=None,negative_prompt=None)
        return self.__oins__.__call__(**kwargs)

def generate_image_and_send_to_telegram(pipeline,prompt,negative_prompt,num,seed=None,use_enhancer=True,**kwargs):
    kwargs.update(prompt=prompt,negative_prompt=negative_prompt)
    seeds = []
    images = []
    if seed:
        seeds.append(seed)
    else:
        for i in range(num):
            seeds.append(randint(-2 ** 63, 2 ** 64 - 1))
    for item in seeds:
        kwargs.update(generator=torch.Generator(pipeline.device).manual_seed(item))
        image = pipeline(**kwargs).images[0] if use_enhancer else pipeline.__oins__(**kwargs).images[0]
        images.append(image)
        caption = f"Prompt: {prompt[:384]}\n\nNegative Prompt: {negative_prompt[:384]}\n\nStep: {kwargs.get('num_inference_steps')}, CFG: {kwargs.get('guidance_scale')}, CLIP Skip: {kwargs.get('clip_skip')}\nSampler: {pipeline.scheduler.config._class_name}\nLoRa: {pipeline.lora_dict}\nSeed: {item}\n\nModel:{pipeline.model_name}"
        threading.Thread(target=lambda: pipeline.send_PIL_photo(image,file_name=f"{pipeline.__class__.__name__}.PNG",file_type="PNG",caption=caption)).start()
    return images

class SDPipelineEnhancer(PipelineEnhancerBase,
                         LoraEnhancerMixin,SDCLIPEnhancerMixin,FromURLMixin,
                         TGBotMixin,UIMixin,EasyInitSubclass):
    overrides = []

    def __init__(self,__oins__):
        PipelineEnhancerBase.__init__(self, __oins__)
        LoraEnhancerMixin.__init__(self)
        SDCLIPEnhancerMixin.__init__(self)
        TGBotMixin.__init__(self)

    def __call__(self,**kwargs):
        if kwargs.get("negative_prompt") is None:
            kwargs.update(negative_prompt="")
        prompt = kwargs.get("prompt")
        negative_prompt = kwargs.get("negative_prompt")
        if isinstance(prompt,list) and isinstance(negative_prompt,list):
            prompt_type = list
        elif isinstance(prompt,list) and not isinstance(negative_prompt,list):
            negative_prompt = [negative_prompt for _ in range(len(prompt))]
            prompt_type = list
        elif not isinstance(prompt,list) and isinstance(negative_prompt,list):
            prompt = [prompt for _ in range(len(negative_prompt))]
            prompt_type = list
        elif isinstance(prompt,str) and isinstance(negative_prompt,str):
            prompt_type = str
        else:
            raise ValueError("The type of prompt and negative_prompt need to be str or list.")

        prompt_str = f"{prompt} {negative_prompt}" if prompt_type == str else f"{' '.join(prompt)} {' '.join(negative_prompt)}"
        saved_lora_dict = self.lora_dict.copy()

        for lora,weight in self.lora_dict.items():
            if lora not in prompt_str:
                self.set_lora_strength(lora, 0)
                print(f"LoRA {lora}:{weight} is disable due to {lora} is not in prompts.")
        try:
            r = SDCLIPEnhancerMixin.__call__(self,**kwargs)
        except Exception as e:
            raise e
        finally:
            for lora,weight in saved_lora_dict.items():
                self.set_lora_strength(lora,weight)
        return r

    def load_i2i_pipeline(self,**kwargs):
        pipeline = PipelineEnhancerBase.load_i2i_pipeline(self,**kwargs)
        pipeline.lora_dict = self.lora_dict
        pipeline.set_telegram_kwargs(**self.telegram_kwargs)
        pipeline.set_download_kwargs(**self.download_kwargs)
        pipeline.load_ui = lambda : None
        return pipeline

    def load_inpainting_pipeline(self,**kwargs):
        pipeline = PipelineEnhancerBase.load_inpainting_pipeline(self,**kwargs)
        pipeline.lora_dict = self.lora_dict
        pipeline.set_telegram_kwargs(**self.telegram_kwargs)
        pipeline.set_download_kwargs(**self.download_kwargs)
        pipeline.load_ui = lambda : None
        return pipeline

    def generate_image_and_send_to_telegram(self,
                                            prompt,negative_prompt="",
                                            guidance_scale=2,num_inference_steps=28,clip_skip=0,
                                            width=None,height=None,
                                            seed=None,num=1,
                                            use_enhancer=True,**kwargs):
        return generate_image_and_send_to_telegram(
            self,
            prompt=prompt,negative_prompt=negative_prompt,
            guidance_scale=guidance_scale,num_inference_steps=num_inference_steps,clip_skip=clip_skip,
            width=width,height=height,
            seed=seed,num=num,
            use_enhancer=use_enhancer,**kwargs)

    @classmethod
    def from_url(cls,url=None,model_version=None,**kwargs):
        return load_stable_diffusion_pipeline(model=url,model_version=model_version,**kwargs)

    def load_ui(self,*args,**kwargs):
        i2i_pipeline = self.load_i2i_pipeline()
        def t2i_fn(prompt, negative_prompt="",
                   guidance_scale=2, num_inference_steps=28, clip_skip=0,
                   width=None, height=None,
                   seed=None, num=1):
            return self.generate_image_and_send_to_telegram(
                                prompt=prompt,negative_prompt=negative_prompt,
                                guidance_scale=guidance_scale,num_inference_steps=num_inference_steps,clip_skip=clip_skip,
                                width=width,height=height,
                                seed=int(seed),num=int(num))

        def i2i_fn(image,
                   prompt,negative_prompt="",
                   strength=0.3,
                   guidance_scale=2,num_inference_steps=28,clip_skip=0,
                   seed=None,num=1):
            image = Image.fromarray(image)
            return i2i_pipeline.generate_image_and_send_to_telegram(
                                image=image,
                                prompt=prompt,negative_prompt=negative_prompt,
                                strength=strength,
                                guidance_scale=guidance_scale,num_inference_steps=num_inference_steps,clip_skip=clip_skip,
                                seed=int(seed),num=int(num))

        fns = {"t2i":t2i_fn,"i2i":i2i_fn}
        server = load_stable_diffusion_ui(fns)
        server.launch(*args,**kwargs)
        return server
