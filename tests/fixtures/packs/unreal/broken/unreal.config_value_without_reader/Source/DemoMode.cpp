#include "DemoSettings.h"
void ADemoMode::Start()
{
    float T = GetDefault<UDemoSettings>()->RoundSeconds;
    StartTimer(T);
}
