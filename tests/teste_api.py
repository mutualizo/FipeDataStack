import csv, time, random, requests

BASE = "https://veiculos.fipe.org.br/api/veiculos"
HDRS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://veiculos.fipe.org.br/",
    "Content-Type": "application/json; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}

TIPO_MAP = {1: "carros", 2: "motos", 3: "caminhoes"}

s = requests.Session(); s.headers.update(HDRS)

def post(path, payload=None):
    r = s.post(f"{BASE}/{path}", json=payload or {})
    r.raise_for_status()
    time.sleep(random.uniform(0.3, 0.7))  # throttle
    return r.json()

def tabela_ref():
    # retorna o último código de referência
    refs = post("ConsultarTabelaDeReferencia")
    return max(int(x["Codigo"]) for x in refs)

def marcas(ref, tipo):
    return post("ConsultarMarcas", {
        "codigoTabelaReferencia": ref,
        "codigoTipoVeiculo": tipo
    })

def modelos(ref, tipo, cod_marca):
    data = post("ConsultarModelos", {
        "codigoTabelaReferencia": ref,
        "codigoTipoVeiculo": tipo,
        "codigoMarca": int(cod_marca),
    })
    return data.get("Modelos", [])

def anos(ref, tipo, cod_marca, cod_modelo):
    return post("ConsultarAnoModelo", {
        "codigoTabelaReferencia": ref,
        "codigoTipoVeiculo": tipo,
        "codigoMarca": int(cod_marca),
        "codigoModelo": int(cod_modelo),
    })

def valor(ref, tipo, cod_marca, cod_modelo, ano_value):
    ano, comb = ano_value.split("-")
    return post("ConsultarValorComTodosParametros", {
        "codigoTabelaReferencia": ref,
        "codigoTipoVeiculo": tipo,
        "codigoMarca": int(cod_marca),
        "codigoModelo": int(cod_modelo),
        "anoModelo": int(ano),
        "codigoTipoCombustivel": int(comb),
        "tipoVeiculo": {1:"carro",2:"moto",3:"caminhao"}[tipo],
        "modeloCodigoExterno": "",
        "tipoConsulta": "tradicional",
    })

def dump(tipo=1, csv_path="fipe_dump.csv", max_marcas=None):
    ref = tabela_ref()
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tipo","mes_referencia","marca","modelo","ano_modelo",
                    "combustivel","codigo_fipe","valor","data_consulta"])
        for i, m in enumerate(marcas(ref, tipo)):
            if max_marcas and i >= max_marcas: break
            cod_marca = m["Value"]; nome_marca = m["Label"]
            for mod in modelos(ref, tipo, cod_marca):
                cod_modelo = mod["Value"]; nome_modelo = mod["Label"]
                for a in anos(ref, tipo, cod_marca, cod_modelo):
                    ano_value = a["Value"]          # ex: "2011-1"
                    resp = valor(ref, tipo, cod_marca, cod_modelo, ano_value)
                    w.writerow([
                        TIPO_MAP[tipo],
                        resp.get("MesReferencia",""),
                        resp.get("Marca", nome_marca),
                        resp.get("Modelo", nome_modelo),
                        resp.get("AnoModelo",""),
                        resp.get("Combustivel",""),
                        resp.get("CodigoFipe",""),
                        resp.get("Valor",""),
                        resp.get("DataConsulta",""),
                    ])

if __name__ == "__main__":
    # exemplo: só carros, limitando a 5 marcas para teste
    dump(tipo=1, csv_path="fipe_carros.csv", max_marcas=5)
