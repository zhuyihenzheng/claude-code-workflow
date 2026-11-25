import static com.tngtech.archunit.base.DescribedPredicate.not;
import static com.tngtech.archunit.core.domain.JavaClass.Predicates.INTERFACES;
import static com.tngtech.archunit.core.domain.JavaClass.Predicates.simpleNameEndingWith;
import static com.tngtech.archunit.core.domain.properties.CanBeAnnotated.Predicates.annotatedWith;
import static com.tngtech.archunit.core.domain.properties.CanBeAnnotated.Predicates.metaAnnotatedWith;
import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses;
import static com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noFields;
import static com.tngtech.archunit.library.GeneralCodingRules.BE_ANNOTATED_WITH_AN_INJECTION_ANNOTATION;

import com.tngtech.archunit.base.DescribedPredicate;
import com.tngtech.archunit.core.domain.JavaClass;
import com.tngtech.archunit.core.importer.ImportOption;
import com.tngtech.archunit.junit.AnalyzeClasses;
import com.tngtech.archunit.junit.ArchTest;
import com.tngtech.archunit.lang.ArchRule;

/**
 * AGENTS.md のレイヤー規約を、コンパイル済みクラスの依存関係で検査する（ArchUnit、./mvnw verify で実行される）。
 *
 * <p>scripts/guard.py は import 文の文字列しか見ないため、同じパッケージ内の参照や完全修飾名での参照はここで止める。
 * パッケージ名に依存しないよう、デフォルトパッケージに置き、Spring のアノテーションとクラス名で層を判定する。
 * 依存関係は config/quality/pom-snippet.xml を参照。
 *
 * <p>既存の違反が多いプロジェクトに導入する場合は、該当ルールを
 * {@code com.tngtech.archunit.library.freeze.FreezingArchRule.freeze(...)} で包み、人が一度だけ
 * {@code ./mvnw test -Dtest=ArchitectureTest -Darchunit.freeze.store.default.allowStoreCreation=true}
 * を実行して、生成された archunit_store をコミットする。以後、記録された違反は縮小だけができる。
 */
@AnalyzeClasses(packages = "", importOptions = {ImportOption.DoNotIncludeTests.class, ImportOption.DoNotIncludeArchives.class})
class ArchitectureTest {

    private static final DescribedPredicate<JavaClass> PERSISTENCE = simpleNameEndingWith("Repository")
            .or(simpleNameEndingWith("Dao"))
            .or(simpleNameEndingWith("DAO"))
            .or(simpleNameEndingWith("Mapper").and(INTERFACES).and(not(annotatedWith("org.mapstruct.Mapper"))))
            .or(annotatedWith("org.apache.ibatis.annotations.Mapper"))
            .or(metaAnnotatedWith("org.springframework.stereotype.Repository"))
            .as("永続化層（Repository、Mapper、DAO）");

    @ArchTest
    static final ArchRule controllers_do_not_use_persistence = noClasses()
            .that().areMetaAnnotatedWith("org.springframework.stereotype.Controller")
            .should().dependOnClassesThat(PERSISTENCE)
            .because("Controller から永続化層を直接使わない。必要な処理を Service のメソッドとして追加し、Controller は Service だけを呼ぶ")
            .allowEmptyShould(true);

    @ArchTest
    static final ArchRule services_do_not_depend_on_controllers = noClasses()
            .that().areMetaAnnotatedWith("org.springframework.stereotype.Service")
            .should().dependOnClassesThat().areMetaAnnotatedWith("org.springframework.stereotype.Controller")
            .because("依存は Controller → Service → 永続化層 の一方向にする。Controller の処理が必要なら Service に移す")
            .allowEmptyShould(true);

    @ArchTest
    static final ArchRule no_field_injection = noFields()
            .should(BE_ANNOTATED_WITH_AN_INJECTION_ANNOTATION)
            .because("依存は private final フィールドにし、コンストラクタの引数で受け取る")
            .allowEmptyShould(true);
}
