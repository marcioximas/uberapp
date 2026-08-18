class TestFormatKmFilter:
    def _km(self, app):
        return app.jinja_env.filters["km"]

    def test_valor_inteiro_nao_mostra_decimal(self, app):
        assert self._km(app)(513) == "513"

    def test_valor_fracionario_mostra_uma_casa_decimal(self, app):
        assert self._km(app)(1060.7) == "1.060,7"

    def test_milhar_usa_ponto_e_decimal_usa_virgula(self, app):
        assert self._km(app)(12345.6) == "12.345,6"

    def test_none_mostra_traco(self, app):
        assert self._km(app)(None) == "-"

    def test_valor_pequeno_fracionario(self, app):
        assert self._km(app)(0.03) == "0,0"
