import RPi.GPIO as GPIO

def berechne_energie(werte):
    return sum(werte) / len(werte)
