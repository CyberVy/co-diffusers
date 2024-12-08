# 0
# !pip install -q git+https://github.com/huggingface/diffusers.git
# !pip install -q git+https://github.com/CyberVy/co-diffusers.git@main#subdirectory=co-diffusers

# 1
from coffusers.enhancement import load_enhancer
from coffusers.const import *
import threading,torch


model = "https://civitai.com/api/download/models/646523?type=Model&format=SafeTensor&size=pruned&fp=fp16"
pipeline = load_enhancer(model,download_kwargs={"headers":{"cookie":cookie}}).to("cuda")

# 2
prompt = """
young white woman with dramatic makeup resembling a melted clown, deep black smokey eyes, smeared red lipstick, and white face paint streaks, wet hair falling over shoulders, dark and intense aesthetic, fashion editorial style, aged around 20 years, inspired by rick genest's zombie boy look, best quality
"""
negative_prompt = """
bad hands, malformed limbs, malformed fingers, bad anatomy, fat fingers, ugly, unreal, cgi, airbrushed, watermark, low resolution
"""
num = 5

num_inference_steps = 30
guidance_scale = 1.5
clip_skip = 1

seed = 13743883683399229202

width = None
height = None

pipeline.set_lora("https://civitai.com/api/download/models/997426?type=Model&format=SafeTensor","hand",0.2)

images = pipeline.generate_image_and_send_to_telegram(prompt=prompt,negative_prompt=negative_prompt,num=num,seed=seed,width=width,height=height,num_inference_steps=num_inference_steps,guidance_scale=guidance_scale,clip_skip=clip_skip)
