import requests
import json
import boto3
import os
import time
import logging
import random

HDRS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://veiculos.fipe.org.br/",
    "Content-Type": "application/json; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}

def mes_ano_formatado(mes, ano):
    # Dicionário com os nomes dos meses em português
    meses = {
        1: "janeiro",
        2: "fevereiro",
        3: "março",
        4: "abril",
        5: "maio",
        6: "junho",
        7: "julho",
        8: "agosto",
        9: "setembro",
        10: "outubro",
        11: "novembro",
        12: "dezembro"
    }
    
    # Verificar se o mês está dentro do intervalo válido (1-12)
    if mes < 1 or mes > 12:
        raise ValueError("Mês deve estar entre 1 e 12")
    
    # Retornar a string formatada
    return f"{meses[mes]}/{ano}"

class FipeAPI:
    # Inicializando o cliente SQS e o logger como atributos de classe
    sqs_client = boto3.client("sqs")
    session = requests.Session()
    session.headers.update(HDRS)
    logger = logging.getLogger(__name__)  # Definindo o nome do logger
    reference_period = (0,0,)
    reference_table = None
    reference_table_code = None
    reference_month_name = None

    def __init__(self, period=None):
        if period== None:
            period = (0,0,)
        self.logger.setLevel(logging.INFO)  # Definindo o nível de log
        self.url_base = os.getenv("URL_FIPE")
        self.logger.info(f"Fipe URL -> {self.url_base}")
        if not bool(self.url_base):
            raise ValueError("Variável de ambiente URL_FIPE nao definida")
        self.reference_period = period
        self.get_reference_table()
    
    def _post(self, url, payload=None):
        response = self.session.post( url, json=payload or {})
        response.raise_for_status()
        time.sleep(random.uniform(0.5, 1.0))  # throttle
        return response.json()

    def get_reference_table(self):
        self.logger.info("REFTABLE - Starting to fetch reference table.")
        try:
            mes = self.reference_period[0]
            ano = self.reference_period[1]
            url = f"{self.url_base}/ConsultarTabelaDeReferencia"
            response = self._post(url)
            self.reference_table = response
            if self.reference_table:
                if mes == 0 and ano == 0:
                    self.reference_table_code = self.reference_table[0].get("Codigo")
                    self.reference_month_name = self.reference_table[0].get(
                        "Mes", "Desconhecido"
                    ).strip()
                else:
                    database = mes_ano_formatado(mes, ano)
                    for table in self.reference_table:
                        if str(table["Mes"]).strip().lower() == database.lower():
                            self.reference_table_code = table.get("Codigo")
                            self.reference_month_name = table.get(
                                "Mes", "Desconhecido"
                            ).strip()
                return True
            else:
                self.logger.warning("REFTABLE - No reference tables found.")
                return False
        except Exception as e:
            self.logger.error(f"REFTABLE - Error fetching reference table: {e}")
            raise

    def get_brands(self, vehicle_type):
        try:
            url = f"{self.url_base}/ConsultarMarcas"
            payload = {
                "codigoTabelaReferencia": self.reference_table_code,
                "codigoTipoVeiculo": vehicle_type,
            }
            self.logger.info(
                f"Fetching brands for vehicle type {vehicle_type} with payload: {payload}"
            )
            response = self._post(url, payload)
            brands = response
            self.logger.info(f"Brands for vehicle type {vehicle_type}: {brands}")
            return brands
        except Exception as e:
            self.logger.error(
                f"Error fetching brands for vehicle type {vehicle_type}: {e}"
            )
            raise

    def get_models(self, brand_code, vehicle_type):
        url = f"{self.url_base}/ConsultarModelos"
        payload = {
            "codigoTabelaReferencia": self.reference_table_code,
            "codigoTipoVeiculo": vehicle_type,
            "codigoMarca": brand_code,
        }
        self.logger.info(f"Querying models with payload: {payload}")
        try:
            response = self._post(url, payload)
            models = response
            self.logger.info(f"Received response: {models}")
            time.sleep(1)  # Adding delay after successful request
            return models
        except requests.RequestException as e:
            self.logger.error(f"Request failed: {e}")
            raise

    def get_years(self, manufacturer_code, model_code, vehicle_type):
        url = f"{self.url_base}/ConsultarAnoModelo"
        payload = {
            "codigoTabelaReferencia": self.reference_table_code,
            "codigoTipoVeiculo": vehicle_type,
            "codigoMarca": manufacturer_code,
            "codigoModelo": model_code,
        }
        self.logger.info(f"Querying years with payload: {payload}")
        response = self._post(url, payload)
        years = response
        self.logger.info(f"Raw API response: {years}")

        if isinstance(years, dict):
            if years.get("erro"):
                self.logger.warning(
                    f"API returned an error for years: {years.get('erro', 'Unknown error')}"
                )
                return [], set()

        processed_years = []
        available_fuel_types = set()

        fuel_type_map = {"Gasolina": "1", "Álcool": "2", "Diesel": "3"}

        for item in years:
            label = item.get("Label", "")
            value = item.get("Value", "")

            # Extrai o ano do label
            year_str = label.split(" ")[0]

            # Verifica se o Value contém um hífen
            if "-" in value:
                fuel_type_number = value.split("-")[-1]  # Extrai o número após o hífen
            else:
                # Se não houver hífen, tenta pegar a palavra após o ano
                fuel_type_from_label = (
                    label.split(" ")[1] if len(label.split(" ")) > 1 else ""
                )

                fuel_type_number = fuel_type_map.get(fuel_type_from_label, "")

            if fuel_type_number:
                available_fuel_types.add(fuel_type_number)

            # Verifica se o ano é válido e adiciona à lista de anos processados
            if year_str.isdigit():
                processed_years.append({"yearModel": year_str, "Label": label})
            else:
                self.logger.warning(f"Ignoring invalid year label: {label}")

        self.logger.info(f"Available fuel types: {available_fuel_types}")
        self.logger.info(f"Years obtained: {processed_years}")
        return processed_years, available_fuel_types

    def get_price(
        self, manufacturer_code, model_code, year_model, vehicle_type, fuel_type
    ):
        """Obtém o preço do veículo para um determinado ano e tipo de combustível."""
        url = f"{self.url_base}/ConsultarValorComTodosParametros"
        payload = {
            "codigoTabelaReferencia": self.reference_table_code,
            "codigoTipoVeiculo": vehicle_type,
            "codigoMarca": manufacturer_code,
            "codigoModelo": model_code,
            "anoModelo": year_model,
            "codigoTipoCombustivel": fuel_type,
            "modeloCodigoExterno": "",
            "tipoConsulta": "tradicional",
        }
        self.logger.info(f"Querying price with payload: {payload}")
        response = self._post(url, payload)
        price = response
        self.logger.info(f"Price obtained: {price}")
        return price

    def send_message_sqs(self, queue_url, message):
        try:
            response = self.sqs_client.send_message(
                QueueUrl=queue_url, MessageBody=json.dumps(message, ensure_ascii=False)
            )
            self.logger.info(f"Message sent to SQS: {message}")
        except Exception as e:
            self.logger.error(f"Error sending message to SQS: {e}")
            raise

    def chunk_list(self, data, chunk_size):
        """Divide uma lista em pedaços menores."""
        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]

    def send_sqs_messages(self, queue_url, messages):
        batch_item_failures = []  # Para registrar falhas
        try:
            entries = [
                {
                    "Id": str(index),
                    "MessageBody": json.dumps(message, ensure_ascii=False),
                }
                for index, message in enumerate(messages)
            ]
            self.logger.info(f"Preparing to send messages in chunks.")

            chunked_entries = self.chunk_list(entries, 10)

            for chunk in chunked_entries:
                self.logger.info(f"Sending batch of messages: {chunk}")
                response = self.sqs_client.send_message_batch(
                    QueueUrl=queue_url, Entries=chunk
                )
                failed_messages = response.get("Failed", [])
                if failed_messages:
                    self.logger.warning(
                        f"Failed to send some messages: {failed_messages}"
                    )
                    # Adiciona falhas ao batch_item_failures
                    for failed in failed_messages:
                        batch_item_failures.append({"itemIdentifier": failed["Id"]})
                self.logger.info(f"Messages sent in batch: {chunk}")

        except Exception as e:
            self.logger.error(f"Error sending messages to SQS: {e}")
            raise
        finally:
            self.logger.info("Finalizing SQS message sending.")

        return batch_item_failures  # Retorna as falhas
