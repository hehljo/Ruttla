#include "DemoHealth.h"
void ADemoVehicle::HitPedestrian(UDemoHealth* Target)
{
    Target->ApplyDamage(50.0f);
}
void ADemoVehicle::Tick(float Dt)
{
    HitPedestrian(nullptr);
}
