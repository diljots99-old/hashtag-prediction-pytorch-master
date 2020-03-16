import os
import time
import argparse
import gdown

import torch
import emoji
import numpy as np
import tensorflow as tf
from tensorflow.keras.preprocessing import image
from torchvision.models import vgg16

from tensorflow.keras.applications.vgg16 import VGG16
from tensorflow.keras.applications.vgg16 import preprocess_input

from flask import Flask, jsonify, request, render_template, url_for

from transformers import AlbertTokenizer, AlbertConfig
from model import HashtagClassifier


from werkzeug import secure_filename
from flask_uploads import UploadSet, configure_uploads, IMAGES


def get_label():
    return [label.strip() for label in open('label.txt', 'r', encoding='utf-8')]


app = Flask(__name__)

PHOTO_FOLDER = 'static'
app.config['UPLOAD_FOLDER'] = PHOTO_FOLDER


photos = UploadSet('photos', IMAGES)
app.config['UPLOADED_PHOTOS_DEST'] = PHOTO_FOLDER
configure_uploads(app, photos)


tokenizer = None
model = None
args = None
label_lst = get_label()

vgg_model = VGG16(weights='imagenet', include_top=False)


DOWNLOAD_URL_MAP = {
    'hashtag': {
        'pytorch_model': ('https://drive.google.com/uc?id=1zs5xGh43KUDnzbw-ntTb4kBU5w8bslI8', 'pytorch_model.bin'),
        'config': ('https://drive.google.com/uc?id=1LVb7BlC3_0jVLei7a8llDH7qIv49wQcs', 'config.json'),
        'training_config': ('https://drive.google.com/uc?id=1uBP_64wdHPb-N6x89LRXLfXdQqoRg75B', 'training_config.bin')
    }
}


def download(url, filename, cachedir='~/hashtag/'):
    f_cachedir = os.path.expanduser(cachedir)
    os.makedirs(f_cachedir, exist_ok=True)
    file_path = os.path.join(f_cachedir, filename)
    if os.path.isfile(file_path):
        print('Using cached model')
        return file_path
    gdown.download(url, file_path, quiet=False)
    return file_path


def download_model(cachedir='~/hashtag/'):
    download(DOWNLOAD_URL_MAP['hashtag']['pytorch_model'][0], DOWNLOAD_URL_MAP['hashtag']['pytorch_model'][1], cachedir)
    download(DOWNLOAD_URL_MAP['hashtag']['config'][0], DOWNLOAD_URL_MAP['hashtag']['config'][1], cachedir)
    download(DOWNLOAD_URL_MAP['hashtag']['training_config'][0], DOWNLOAD_URL_MAP['hashtag']['training_config'][1], cachedir)


def init_model(cachedir='~/hashtag/', no_cuda=True):
    global tokenizer, model

    f_cachedir = os.path.expanduser(cachedir)
    bert_config = AlbertConfig.from_pretrained(f_cachedir)
    model = HashtagClassifier.from_pretrained(f_cachedir, config=bert_config)
    device = "cuda" if torch.cuda.is_available() and not no_cuda else "cpu"
    model.to(device)
    model.eval()

    tokenizer = AlbertTokenizer.from_pretrained('albert-base-v2')


def convert_texts_to_tensors(texts, max_seq_len, no_cuda=True):
    input_ids = []
    attention_mask = []
    token_type_ids = []
    for text in texts:
        input_id = tokenizer.encode(text, add_special_tokens=True)
        input_id = input_id[:max_seq_len]

        attention_id = [1] * len(input_id)

        # Zero padding
        padding_length = max_seq_len - len(input_id)
        input_id = input_id + ([tokenizer.pad_token_id] * padding_length)
        attention_id = attention_id + ([0] * padding_length)

        input_ids.append(input_id)
        attention_mask.append(attention_id)
        token_type_ids.append([0]*max_seq_len)

    # Change list to torch tensor
    device = "cuda" if torch.cuda.is_available() and not no_cuda else "cpu"

    input_ids = torch.tensor(input_ids, dtype=torch.long).to(device)
    attention_mask = torch.tensor(attention_mask, dtype=torch.long).to(device)
    token_type_ids = torch.tensor(token_type_ids, dtype=torch.long).to(device)
    return input_ids, attention_mask, token_type_ids


def img_to_tensor(img_path, no_cuda):
    img = image.load_img(img_path, target_size=(224, 224))
    img_data = image.img_to_array(img)
    img_data = np.expand_dims(img_data, axis=0)
    img_data = preprocess_input(img_data)

    vgg16_feature = vgg_model.predict(img_data)

    feat = np.transpose(vgg16_feature, (0, 3, 1, 2))
    # Change list to torch tensor
    device = "cuda" if torch.cuda.is_available() and not no_cuda else "cpu"
    return torch.tensor(feat, dtype=torch.float).to(device)


@app.route("/predict", methods=["POST", "GET"])
def predict():
    img_id = request.args.get('image_id')
    text = request.args.get('text')
    max_seq_len = int(request.args.get('max_seq_len'))
    n_label = int(request.args.get('n_label'))

    # Prediction
    img_link = "https://drive.google.com/uc?id={}".format(img_id)
    download(img_link, "{}.jpg".format(img_id), cachedir=app.config['UPLOAD_FOLDER'])
    img_tensor = img_to_tensor(os.path.join(app.config['UPLOAD_FOLDER'], "{}.jpg".format(img_id)), args.no_cuda)

    texts = [emoji.demojize(text.lower())]

    input_ids, attention_mask, token_type_ids = convert_texts_to_tensors(texts, max_seq_len, args.no_cuda)
    with torch.no_grad():
        outputs = model(input_ids, attention_mask, token_type_ids, None, img_tensor)
    logits = outputs[0]

    _, top_idx = logits.topk(n_label)

    preds = []
    print(top_idx)
    for idx in top_idx[0]:
        preds.append("#{}".format(label_lst[idx]))

    return render_template("result.html", user_image="./{}/{}".format(app.config['UPLOAD_FOLDER'], "{}.jpg".format(img_id)), text=text, tag=" ".join(preds))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("-p", "--port_num", type=int, default=80, help="Port Number")
    parser.add_argument("-n", "--no_cuda", action="store_true", help="Avoid using CUDA when available")
    args = parser.parse_args()

    download_model()
    print("Initializing the model...")
    init_model(no_cuda=args.no_cuda)

    app.run(debug=False)
