#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

import io
import logging
import re
from email import policy
from email.parser import BytesParser
from timeit import default_timer as timer

from app.deepdoc.parser import HtmlParser, TxtParser
from app.third_party.integrated_pipeline.chunkers.naive import chunk as naive_chunk
from app.third_party.integrated_pipeline.nlp import naive_merge, rag_tokenizer, tokenize_chunks


def _build_doc(filename):
    doc = {
        "docnm_kwd": filename,
        "title_tks": rag_tokenizer.tokenize(re.sub(r"\.[a-zA-Z]+$", "", filename)),
    }
    doc["title_sm_tks"] = rag_tokenizer.fine_grained_tokenize(doc["title_tks"])
    return doc


def _load_message(filename, binary):
    if binary:
        with io.BytesIO(binary) as buffer:
            return BytesParser(policy=policy.default).parse(buffer)
    with open(filename, "rb") as buffer:
        return BytesParser(policy=policy.default).parse(buffer)


def _decode_payload(payload, charset):
    try:
        return payload.decode(charset)
    except (UnicodeDecodeError, LookupError):
        for enc in ["utf-8", "gb2312", "gbk", "gb18030", "latin1"]:
            try:
                return payload.decode(enc)
            except UnicodeDecodeError:
                continue
    return payload.decode("utf-8", errors="ignore")


def _append_part_content(message, text_txt, html_txt):
    content_type = message.get_content_type()
    if content_type == "text/plain":
        payload = message.get_payload(decode=True)
        charset = message.get_content_charset() or "utf-8"
        text_txt.append(_decode_payload(payload, charset))
        return
    if content_type == "text/html":
        payload = message.get_payload(decode=True)
        charset = message.get_content_charset() or "utf-8"
        html_txt.append(_decode_payload(payload, charset))
        return
    if "multipart" in content_type and message.is_multipart():
        for part in message.iter_parts():
            _append_part_content(part, text_txt, html_txt)


def _collect_sections(message):
    text_txt = [f"{header}: {value}" for header, value in message.items()]
    html_txt = []
    _append_part_content(message, text_txt, html_txt)

    html_sections = []
    if any(str(line or "").strip() for line in html_txt):
        html_sections = [(line, "") for line in HtmlParser.parser_txt("\n".join(html_txt)) if line]
    return TxtParser.parser_txt("\n".join(text_txt)) + html_sections


def _chunk_attachments(message, callback, kwargs):
    attachment_res = []
    for part in message.iter_attachments():
        content_disposition = part.get("Content-Disposition")
        if not content_disposition:
            continue
        dispositions = content_disposition.strip().split(";")
        if dispositions[0].lower() != "attachment":
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True)
        try:
            attachment_res.extend(naive_chunk(filename, payload, callback=callback, **kwargs))
        except Exception as exc:
            logging.debug("Failed to chunk email attachment %s: %s", filename, exc)
    return attachment_res


def chunk(
    filename,
    binary=None,
    from_page=0,
    to_page=100000,
    lang="Chinese",
    callback=None,
    **kwargs,
):
    """
    Only eml is supported
    """
    _ = (from_page, to_page)
    eng = lang.lower() == "english"  # is_english(cks)
    parser_config = kwargs.get(
        "parser_config",
        {"chunk_token_num": 512, "delimiter": "\n!?。；！？", "layout_recognize": "DeepDOC"},
    )
    doc = _build_doc(filename)
    msg = _load_message(filename, binary)
    sections = _collect_sections(msg)

    st = timer()
    chunks = naive_merge(
        sections,
        int(parser_config.get("chunk_token_num", 128)),
        parser_config.get("delimiter", "\n!?。；！？"),
    )

    main_res = tokenize_chunks(chunks, doc, eng, None)
    logging.debug("naive_merge({}): {}".format(filename, timer() - st))
    return main_res + _chunk_attachments(msg, callback, kwargs)


if __name__ == "__main__":
    import sys

    def dummy(prog=None, msg=""):
        pass

    chunk(sys.argv[1], callback=dummy)
