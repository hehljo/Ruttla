#include "DemoHealth.h"
UCLASS()
class UDemoHealth : public UActorComponent { GENERATED_BODY() };
float UDemoHealth::ApplyDamage(float Amount)
{
    Health -= Amount;
    return Amount;
}
