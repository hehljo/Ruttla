#include "DemoChar.h"
UCLASS()
class ADemoChar : public ACharacter { GENERATED_BODY() };
ADemoChar::ADemoChar()
{
    VisibleBody = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Body"));
    VisibleBody->SetupAttachment(GetMesh());
    VisibleHead = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Head"));
    VisibleHead->SetupAttachment(GetMesh());
}
