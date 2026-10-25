"""Leitor do boletim de urna (BU) publicado pelo TSE em arquivo-urna/.../*-bu.dat.

O arquivo é DER (ASN.1): um envelope genérico cujo último campo (OCTET STRING) traz o BU.
Em vez de depender da posição exata de cada campo, procura as estruturas pelo conteúdo:

  ResultadoVotacaoPorEleicao  SEQ { idEleicao INTEGER, qtdEleitoresAptos INTEGER, ... }
  ResultadoVotacao            SEQ { tipoCargo ENUM, qtdComparecimento INTEGER, totaisVotosCargo ... }
  VotoVotavel                 SEQ { [1] tipoVoto, [2] quantidadeVotos, [3] { partido, codigo }?, ... }

tipoVoto: 1 nominal, 2 branco, 3 nulo, 4 legenda. Conferido no BU de Wellington (seção 1088):
60 + 13 votos nominais = 73 de comparecimento.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class No:
    classe: int        # 0 universal, 0x80 contexto
    tag: int
    composto: bool
    valor: bytes
    filhos: list


def _ler(b: bytes, i: int, fim: int) -> list:
    out = []
    while i < fim:
        t = b[i]; i += 1
        if t & 0x1F == 0x1F:
            n = 0
            while True:
                x = b[i]; i += 1
                n = (n << 7) | (x & 0x7F)
                if not x & 0x80:
                    break
            tag = n
        else:
            tag = t & 0x1F
        ln = b[i]; i += 1
        if ln & 0x80:
            k = ln & 0x7F
            ln = int.from_bytes(b[i:i + k], "big"); i += k
        v = b[i:i + ln]
        composto = bool(t & 0x20)
        filhos = _ler(b, i, i + ln) if composto else []
        # OCTET STRING com um DER dentro (o conteúdo do envelope)
        if not composto and t & 0xC0 == 0 and tag == 4 and v[:1] == b"\x30":
            try:
                filhos = _ler(v, 0, len(v))
            except (IndexError, ValueError):
                filhos = []
        out.append(No(t & 0xC0, tag, composto, v, filhos))
        i += ln
    return out


def _int(n: No) -> int:
    return int.from_bytes(n.valor, "big", signed=True)


def _todos(nos: list):
    for n in nos:
        yield n
        yield from _todos(n.filhos)


def ler_bu(b: bytes, eleicao: int = 6258) -> dict:
    """Devolve aptos, comparecimento e votos por candidato (número), brancos e nulos da eleição pedida."""
    raiz = _ler(b, 0, len(b))
    res = None
    for n in _todos(raiz):
        f = n.filhos
        if n.classe == 0 and n.tag == 16 and len(f) >= 2 and f[0].classe == 0 and f[0].tag == 2 \
                and not f[0].composto and _int(f[0]) == eleicao:
            res = n
            break
    if res is None:
        raise ValueError(f"BU sem resultado da eleição {eleicao}")
    aptos = _int(res.filhos[1])

    comp = None
    votos: dict[str, int] = {}
    brancos = nulos = 0
    for n in _todos(res.filhos):
        f = n.filhos
        # ResultadoVotacao: ENUM tipoCargo, INTEGER comparecimento, SEQ totais
        if comp is None and n.tag == 16 and len(f) >= 3 and f[0].tag == 10 and f[1].tag == 2 and f[2].tag == 16:
            comp = _int(f[1])
        ctx = {c.tag: c for c in f if c.classe == 0x80}
        if n.tag == 16 and 1 in ctx and 2 in ctx and not ctx[1].composto:
            tipo, qtd = _int(ctx[1]), _int(ctx[2])
            if tipo == 1 and 3 in ctx:
                cod = _int(ctx[3].filhos[1]) if len(ctx[3].filhos) > 1 else _int(ctx[3].filhos[0])
                votos[str(cod)] = votos.get(str(cod), 0) + qtd
            elif tipo == 2:
                brancos += qtd
            elif tipo == 3:
                nulos += qtd
    total = sum(votos.values()) + brancos + nulos
    if comp is not None and total != comp:
        raise ValueError(f"BU não fecha: votos {total} != comparecimento {comp}")
    return {"aptos": aptos, "comp": comp if comp is not None else total, "votos": votos,
            "brancos": brancos, "nulos": nulos}


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(ler_bu(open(sys.argv[1], "rb").read()), indent=1))
