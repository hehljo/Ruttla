#include "DemoCtrl.h"
UCLASS()
class ADemoCtrl : public APlayerController { GENERATED_BODY() };
void ADemoCtrl::Bind(UPrimitiveComponent* Mesh)
{
    Mesh->SetNotifyRigidBodyCollision(true);
    Mesh->OnComponentHit.AddDynamic(this, &ADemoCtrl::HandleHit);
}
