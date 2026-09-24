#include "DemoChar.h"
UCLASS()
class ADemoChar : public ACharacter { GENERATED_BODY() };
ADemoChar::ADemoChar()
{
    static ConstructorHelpers::FObjectFinder<USkeletalMesh> BaseMesh(
        TEXT("/Game/Character/SKM_Base.SKM_Base"));
    if (BaseMesh.Succeeded())
    {
        GetMesh()->SetSkeletalMeshAsset(BaseMesh.Object);
    }
}
