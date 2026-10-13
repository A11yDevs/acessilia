"""Políticas de fusão multi-provider.

Os defaults são conservadores/neutros. Os conjuntos de flags calibrados
contra o benchmark Dr.DocBench (PR #98, variantes v3..v13) ficam como
presets nomeados — nunca como default — porque foram sobreajustados ao
split dev (gap dev→test ≈ −6).
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Literal


@dataclass(frozen=True)
class FusionPolicy:
    """Configuração imutável da fusão e dos filtros de ruído.

    Agrupada por preocupação: alinhamento, escolha de texto, reconstrução,
    ruído, fórmulas e rotação.
    """

    # --- Alinhamento (núcleo do Tree Differ) ---
    align_lambda: float = 0.5  # peso texto vs bbox na similaridade
    align_tau: float = 0.6  # limiar de pareamento Húngaro

    # --- Escolha de texto por bloco ---
    text_pick: Literal["auto", "docling", "mineru"] = "auto"
    pick_guard: float = 0.0  # >0: proteção contra Docling engolir colunas (ratio)

    # --- Reconstrução de parágrafos/colunas ---
    merge_paragraphs: bool = True
    fuse_lines: bool = False
    fuse_h_ratio: float = 0.8

    # --- Ruído ---
    decor_tail: bool = True  # header/footer movidos ao fim da página
    running_heads: bool = True
    pagenum_cap: bool = True
    junk_filter: bool = True
    suppress_regions: bool = True  # texto Docling dentro de tabela/figura MinerU
    pic_need_text: bool = True  # exceto quando o provider não leu texto na página
    # Calibração do suppress-in-region (porta fiel do tree_differ_v2):
    pic_min_blocks: int = 2  # nº mínimo de blocos Docling dentro da figura
    pic_max_quality: float = 0.7  # qualidade média abaixo da qual suprime
    pic_full_page: float = 0.9  # figura cobrindo a página toda (comics)
    pic_rule: Literal["count-or-quality", "quality"] = "count-or-quality"
    table_full_page: float = 0.0  # tabela gigante = flyer mal detectado
    table_probe: bool = False  # só suprime se a tabela capturou o texto

    # --- Reconstrução: parâmetros finos ---
    merge_frac: float = 0.6  # contenção para re-fusão de parágrafos
    merge_min_sim: float = 0.0
    fuse_max_len: int = 0  # cap de blocos fundidos (0 = ilimitado)
    fuse_short: int = 80
    fuse_min_run: int = 3
    garbage_frac: float = 0.0  # fallback para ordem Docling quando nada casa

    # --- Fórmulas ---
    formula_text: bool = True  # fórmulas sem operador matemático → texto
    inline_math_promote: bool = True  # parágrafo inteiro com math → display

    # --- Rotação ---
    orientation_min_confidence: float = 0.85
    orientation_reinfer: bool = True

    # --- Reading order ---
    # XY-cut over the fused page: "multicol" reorders only pages whose boxes form
    # at least ``xycut_min_columns`` columns; "always" reorders every page.
    order_xycut: Literal["off", "multicol", "always"] = "off"
    xycut_min_columns: int = 2
    xycut_min_balance: float = 0.0  # >0: skip pages whose columns differ too much in width

    # --- Pós-processamento determinístico (PR #125) ---
    # Os defaults abaixo são os de PRODUÇÃO: as capacidades determinísticas com
    # evidência de ganho (ou correção de defeito) ficam ligadas. As que consomem
    # modelo ficam desligadas e são ligadas quando a Toolbox expõe a capacidade.
    verse_chunk: int = 300  # >0: divide blocos de verso/registro em pedaços <= N chars
    verse_kind: Literal["records", "all"] = "records"  # "records" preserva verso real inteiro
    line_numbers: bool = True  # extrai números de linha marginais para blocos próprios
    table_eq: bool = True  # desembrulha <eq>..</eq> em células de tabela do MinerU
    norm_text: bool = True  # limpezas determinísticas (ligaduras, hífen suave, NBSP)
    hf_end: bool = True  # cabeçalho/rodapé/número de página ao fim da página
    tailjoin: Literal["off", "num", "end", "any"] = "end"  # junta a cauda de blocos curtos
    tailjoin_max_len: int = 50
    tailjoin_k: int = 3
    tailjoin_bot: Literal["keep", "hdr"] = "hdr"  # comportamento com o número no rodapé
    rep_guard: bool = True  # corta repetição degenerada (loops de geração)
    rep_reps: int = 5
    rep_max_n: int = 12
    blank_pages: bool = True  # esvazia páginas em branco detectadas

    # --- Híbrido de página (PR #125) ---
    # Consome modelo: desligado por default, ligado quando a Toolbox expõe a
    # capacidade (document.adjudicate.page / document.ocr.page).
    page_judge: bool = False  # juiz pareado por VLM decide a página
    page_judge_new_thr: float = 0.5
    page_judge_old_thr: float = 0.2
    page_select_dm: float = 0.6  # concordância Docling/MinerU abaixo da qual vale a VLM
    page_swap_agree_thr: float = 0.45  # concordância abaixo da qual a fonte alternativa substitui
    page_swap_min_alt_frac: float = 0.3

    # --- Imagem (decisão pura; aplicação no backend) ---
    # Determinístico e com o maior ganho isolado da linha Tele: ligado.
    upscale: bool = True  # amplia páginas pequenas antes do OCR
    orientation: bool = True  # detecta e corrige rotação 0/90/270

    def __post_init__(self) -> None:
        if not 0.0 <= self.align_lambda <= 1.0:
            raise ValueError(f"align_lambda deve estar em [0,1], got {self.align_lambda}")
        if not 0.0 < self.align_tau <= 1.0:
            raise ValueError(f"align_tau deve estar em (0,1], got {self.align_tau}")
        if self.order_xycut not in ("off", "multicol", "always"):
            raise ValueError(f"order_xycut must be off|multicol|always, got {self.order_xycut!r}")
        if self.verse_kind not in ("records", "all"):
            raise ValueError(f"verse_kind must be records|all, got {self.verse_kind!r}")
        if self.tailjoin not in ("off", "num", "end", "any"):
            raise ValueError(f"tailjoin must be off|num|end|any, got {self.tailjoin!r}")
        if self.tailjoin_bot not in ("keep", "hdr"):
            raise ValueError(f"tailjoin_bot must be keep|hdr, got {self.tailjoin_bot!r}")
        if self.verse_chunk < 0:
            raise ValueError(f"verse_chunk must be >= 0, got {self.verse_chunk}")
        if not 0.0 <= self.xycut_min_balance <= 1.0:
            raise ValueError(f"xycut_min_balance must be in [0,1], got {self.xycut_min_balance}")
        if self.xycut_min_columns < 2:
            raise ValueError(f"xycut_min_columns must be >= 2, got {self.xycut_min_columns}")
        if self.fuse_lines and not self.merge_paragraphs:
            raise ValueError("fuse_lines sem merge_paragraphs é no-op: combinação inválida")

    def to_dict(self) -> dict[str, Any]:
        """Serialização para logs/config/tools Agno."""
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FusionPolicy":
        """Constrói a partir de dict, ignorando chaves desconhecidas."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def drbench_v12(cls) -> "FusionPolicy":
        """Preset do differ-v12 (calibrado no dev do Dr.DocBench — NÃO usar
        como default de produção)."""
        return cls(
            align_lambda=0.5,
            align_tau=0.6,
            text_pick="auto",
            pick_guard=1.5,
            merge_paragraphs=True,
            fuse_lines=True,
            fuse_h_ratio=0.6,
            fuse_max_len=300,
            decor_tail=True,
            running_heads=True,
            pagenum_cap=True,
            junk_filter=True,
            suppress_regions=True,
            pic_need_text=False,
            formula_text=False,
            inline_math_promote=True,
            pic_min_blocks=4,
            pic_rule="quality",
            garbage_frac=0.3,
        )

    @classmethod
    def drbench_v13(cls) -> "FusionPolicy":
        """Preset do differ-v13 (pic-need-text + formula-text ativados)."""
        return cls(
            **{**cls.drbench_v12().to_dict(), "pic_need_text": True, "formula_text": True}
        )

    @classmethod
    def drbench_v14(cls) -> "FusionPolicy":
        """Preset do differ-v14: v13 + os pós-processamentos determinísticos da
        PR #125 (números de linha, ``<eq>`` em tabelas, chunking de verso).

        Calibrado no dev do Dr.DocBench — NÃO usar como default de produção.
        """
        return cls(
            **{
                **cls.drbench_v13().to_dict(),
                "line_numbers": True,
                "table_eq": True,
                "verse_chunk": 300,
                "verse_kind": "records",
            }
        )

    @classmethod
    def drbench_v15(cls) -> "FusionPolicy":
        """Preset do differ-v15: v14 + o híbrido de página e a regra ``tj3``.

        É o melhor confirmado no leaderboard (EvalAI 70.37, ``differ-v15-hyb``).
        Calibrado no dev do Dr.DocBench — NÃO usar como default de produção.
        """
        return cls(
            **{
                **cls.drbench_v14().to_dict(),
                "page_judge": True,
                "tailjoin": "end",
                "tailjoin_max_len": 50,
                "tailjoin_k": 3,
                "tailjoin_bot": "hdr",
                "rep_guard": True,
                "hf_end": True,
                "upscale": True,
                "orientation": True,
            }
        )

    @classmethod
    def drbench_best_method(cls) -> "FusionPolicy":
        """Preset do melhor método do loop (dev 87.33, ``hyb-v29-judge2-televm-adf-tj3``).

        Composição: v13-pnt sobre ``docling-v3+rot`` x ``mineru-hyb+rot``, com
        seleção de página VLM, ``rep_guard``, adição de número de página, juiz
        pareado ``judge2`` (nova > 0.5, senão antiga > 0.2), TeleOCR com upscale
        2x/1.5x e ``tailjoin3``.

        **NUNCA usar como default.** Este resultado nunca foi confirmado no
        leaderboard: o gap dev->test observado é de ~8 pontos, e o TEDS não
        transferiu (dev +5.9 -> test +0.2). O melhor *confirmado* é
        ``drbench_v15`` (EvalAI 70.37). Use este preset apenas para retomar os
        testes de performance, sempre com confirmação no leaderboard antes de
        qualquer promoção.
        """
        return cls(
            **{
                **cls.drbench_v15().to_dict(),
                "page_judge_new_thr": 0.5,
                "page_judge_old_thr": 0.2,
                "page_select_dm": 0.6,
                "page_swap_agree_thr": 0.45,
                "page_swap_min_alt_frac": 0.3,
                "rep_reps": 5,
                "rep_max_n": 12,
                "blank_pages": True,
                "norm_text": True,
            }
        )
