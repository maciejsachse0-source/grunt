"""Deduplikacja cross-portal (sekcja 4.3 dokumentu).

Podzial jak w reszcie projektu: keys.py, pairing.py i cluster.py to funkcje
czyste (bez bazy, bez sieci, bez zegara), a pipeline.py jest jedynym miejscem,
ktore czyta i zapisuje do bazy.
"""
