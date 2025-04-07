# -*- coding: utf-8 -*-
###################################################
#  __  __       _               _ _               #
# |  \/  |_   _| |_ _   _  __ _| (_)_______       #
# | |\/| | | | | __| | | |/ _` | | |_  / _ \      #
# | |  | | |_| | |_| |_| | (_| | | |/ / (_) |     #
# |_|  |_|\__,_|\__|\__,_|\__,_|_|_/___\___/      #
#                                                 #
###################################################

"""
FipeAPI - Módulo para processamento de dados da tabela FIPE.

Este pacote contém as seguintes Lambdas:
- fipe_manufacturer_loader: Carrega fabricantes da API FIPE
- fipe_model_loader: Carrega modelos da API FIPE
- fipe_price_loader: Carrega preços da API FIPE
- fipe_soma_ingestor: Insere dados da API FIPE no banco de dados

Além das funções de suporte:
- fipe_api_service: Cliente para a API FIPE
- get_db_password: Utilitário para obter a senha do banco de dados do Secrets Manager
"""

__version__ = '1.0.0'
