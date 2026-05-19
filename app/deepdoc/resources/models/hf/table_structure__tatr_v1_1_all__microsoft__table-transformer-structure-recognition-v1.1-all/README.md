---
license: mit
---

# Table Transformer (pre-trained for Table Structure Recognition)

Table Transformer (TATR) model trained on PubTables1M and FinTabNet.c. It was introduced in the paper [Aligning benchmark datasets for table structure recognition](https://arxiv.org/abs/2303.00716) by Smock et al. and first released in [this repository](https://github.com/microsoft/table-transformer).

Disclaimer: The team releasing Table Transformer did not write a model card for this model so this model card has been written by the Hugging Face team.

## Model description

The Table Transformer is equivalent to [DETR](https://huggingface.co/docs/transformers/model_doc/detr), a Transformer-based object detection model. Note that the authors decided to use the "normalize before" setting of DETR, which means that layernorm is applied before self- and cross-attention.

## Usage

You can use the raw model for detecting tables in documents. See the [documentation](https://huggingface.co/docs/transformers/main/en/model_doc/table-transformer) for more info.
